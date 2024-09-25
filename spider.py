from datetime import datetime, timedelta
import time
from difflib import SequenceMatcher
import requests
from database import ParsingItem, App, Crawl, Product, Similarity, db
from parse import Parser, get_unit_products, AISimilar


parser = Parser()
ai = AISimilar()


def similarity(a, b):
    a, b = a.lower().split(), b.lower().split()
    a, b = (a, b) if len(a) > len(b) else (b, a)
    answer = 0
    for i in b:
        for x in a:
            if SequenceMatcher(None, i, x).ratio() > .5:
                answer += 1
    answer = answer/len(b)
    return answer


def run_spider():
    while True:
        db.connect(True)
        old_crawlers = Crawl.select().where(Crawl.created_at < (datetime.now() - timedelta(days=3)))
        dq = (Product
            .delete()
            .where(Product.crawlid.in_(old_crawlers)))
        dq.execute()


        urls = [x.link for x in ParsingItem.select()]
        crawl = (
            Crawl
            .select()
            .where(Crawl.finished == True)
            .order_by(Crawl.created_at.desc())
            .first()
        )
        print(crawl.created_at)
        if crawl and crawl.created_at < datetime.now() - timedelta(hours=10):
            crawl = Crawl.create()
            crawlid = crawl.get_id()
            while urls:
                scrape_url = urls.pop()
                app = App.create(
                    name = 'Ozon',
                    start_url = scrape_url
                )
                appid = app.get_id()
                while True:
                    try:
                        print(f'Scraping url: {scrape_url}')
                        parser.parse_product_list(scrape_url, appid, crawlid)
                        break
                    except Exception as e:
                        print(f'Error occurred while scraping: {e}')
                        time.sleep(5)

                if urls: time.sleep(60)

            db.connect(True)
            crawl.finished = True
            crawl.save()

        query = list(Product
            .select()
            .where(Product.crawlid == crawl)
        )

        similars = {}
        for sim in Similarity.select():
            if sim.productId in similars:
                similars[sim.productId].append(sim.unitArticle)
            else:
                similars[sim.productId] = [sim.unitArticle]

        print('Checking for similarity')
        for uprod in get_unit_products():
            for old_prod in Similarity.select().where(Similarity.unitArticle == uprod['article']):
                if old_prod.uprice != uprod['price']:
                    old_prod.uprice = uprod['price']

            likes = []
            for prod in query:
                old_sims = similars.get(prod.productId, [])
                if uprod['article'] in old_sims: continue
                if similarity(prod.name, uprod['name']) >= 0.7:
                    likes.append(prod)
            
            if likes:
                similar = ai.check_products(likes, uprod)
                if similar:
                    payload = {uprod['article']: []}
                    for productId in similar:
                        Similarity.create(
                            productId = productId,
                            unitArticle = uprod['article'],
                            uprice = uprod['price']
                        )
                        prod_data = Product.get(productId=productId)
                        payload[uprod['article']].append(prod_data.productUrl)
                    try:
                        stas_response = requests.post('http://92.53.64.89:5003/recieve_ozon_competitors', json=payload, timeout=3)
                        print(stas_response.status_code, stas_response.content[:50])
                    except Exception as e: print('Reciving system error')
        print('Finished checking')
        time.sleep(60*60)


if __name__ == '__main__':
    db.register_function(similarity, 'similarity', 2)
    while True:
        try: 
            run_spider()
        except Exception as e:
            print(f'Unexpected exception occurred {e}')
        time.sleep(5)
