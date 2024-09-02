from datetime import datetime, timedelta
import json
import time
from database import ParsingItem, App, Crawl, db, Product
from parse import Parser


parser = Parser()

def run_spider():
    while True:
        db.connect(True)
        old_crawlers = Crawl.select().where(Crawl.created_at < (datetime.now() - timedelta(days=3)))
        dq = (Product
            .delete()
            .where(Product.crawlid.in_(old_crawlers)))
        dq.execute()
        try:
            urls = json.loads(open(f'tasks.json', 'rb').read())
            if not urls: raise FileNotFoundError
            
            crawl: Crawl = (
                Crawl
                .select()
                .where(Crawl.finished == False)
                .order_by(Crawl.created_at.desc())
                .first()
            )
        except FileNotFoundError:
            urls = [x.link for x in ParsingItem.select()]
            crawl = Crawl.create()

        crawlid = crawl.get_id()
        db.close()
        open('tasks.json', 'w', -1, 'utf8').write(json.dumps(urls))

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

            open('tasks.json', 'w', -1, 'utf8').write(json.dumps(urls))
            time.sleep(60)

        db.connect(True)
        crawl.finished = True
        crawl.save()
        db.close()
        
        time.sleep(60*60)


if __name__ == '__main__':
    while True:
        try: run_spider()
        except Exception as e: print(f'Unexpected exception occurred {e}')
        time.sleep(5)
