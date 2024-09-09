from datetime import datetime, timedelta
import json
import time
from difflib import SequenceMatcher
from peewee import fn, JOIN
from database import ParsingItem, App, Crawl, Product, Similarity, db
from parse import Parser, get_unit_products, AISimilar


parser = Parser()
ai = AISimilar()


def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def run_spider():
    while True:
        db.connect(True)
        old_crawlers = Crawl.select().where(Crawl.created_at < (datetime.now() - timedelta(days=3)))
        dq = (Product
            .delete()
            .where(Product.crawlid.in_(old_crawlers)))
        dq.execute()
        urls = [x.link for x in ParsingItem.select()]
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

            time.sleep(60)

        db.connect(True)
        crawl.finished = True
        crawl.save()

        for uprod in get_unit_products():
            for old_prod in Similarity.select().where(Similarity.unitArticle == uprod['article']):
                if old_prod.uprice != uprod['price']:
                    old_prod.uprice = uprod['price']

            query = (Product
                .select()
                .join(Similarity, JOIN.LEFT_OUTER, on=(Similarity.productId == Product.productId))
                .where(
                    (fn.similarity(Product.name, uprod['name']) >= 0.7)
                     & (Product.crawlid == crawl)
                     & (Similarity.unitArticle != uprod['article'])
                )
            )
            if query:
                similar = ai.check_products(query)
                for productId in similar:
                    Similarity.create(
                        productId = productId,
                        unitArticle = uprod['article'],
                        uprice = uprod['price']
                    )
        
        time.sleep(60*60)


if __name__ == '__main__':
    db.register_function(similarity, 'similarity', 2)
    while True:
        try: run_spider()
        except Exception as e: print(f'Unexpected exception occurred {e}')
        time.sleep(5)
