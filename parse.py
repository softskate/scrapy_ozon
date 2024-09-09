import json
import time
import requests
import google.generativeai as genai
from database import Product, Crawl
from database import Product, ProductDetails, Similarity
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from keys import *


def remove_url_parameter(url, param_to_remove):
    # Parse the URL into its components
    parsed_url = urlparse(url)
    
    # Parse the query string into a dictionary
    query_params = parse_qs(parsed_url.query)
    
    # Remove the specified parameter
    if param_to_remove in query_params:
        del query_params[param_to_remove]
    
    # Reconstruct the query string
    new_query_string = urlencode(query_params, doseq=True)
    
    # Rebuild the URL without the removed parameter
    new_url = urlunparse(parsed_url._replace(query=new_query_string))
    
    return new_url


class Parser:
    sess = requests.Session()
    headers = {
        "User-Agent":"PostmanRuntime/7.40.0",
        "Accept":"*/*",
        "Connection":"keep-alive"
    }
    sess.headers.update(headers)
    last_init = 0

    def make_req(self, **kwargs):
        resp = self.sess.get("https://www.ozon.ru/api/composer-api.bx/page/json/v2", params=kwargs)
        print('GET->', resp.request.url)
        print(resp.status_code, resp.content[:100])
        return resp.json()


    def parse_product_list(self, url, appid, crawlid, page=None):
        if page is None:
            js_data = self.make_req(url=url)
        else:
            js_data = self.make_req(url=url, page=page)

        js_data = js_data['widgetStates']
        page_data = {'items': []}
        next_page = {}
        for key in js_data:
            if key.startswith('searchResultsV2'):
                page_data = json.loads(js_data[key])
            
            elif key.startswith('megaPaginator'):
                next_page = json.loads(js_data[key])

        for prod in page_data['items']:
            link = 'https://ozon.ru' + prod['action']['link']
            sku = prod['skuId']
            name = ''
            image = ''
            price = 0
            for state in prod['mainState']:
                in_data = state['atom']
                if state.get('id') == 'name':
                    name = in_data['textAtom']['text'].replace('&#x2F;', '/')

            for state in prod['rightState']:
                if state['atom']['type'] == 'priceV2':
                    for price_data in state['atom']['priceV2']['price']:
                        if price_data['textStyle'] == 'PRICE':
                            price_data = price_data['text']
                            for x in ' ₽.,':
                                price_data = price_data.replace(x, '')
                            price = int(price_data)

            for img in prod['tileImage']['items']:
                if img['type'] == 'image':
                    image = img['image']['link']
                    break
            
            uprod = Similarity.get_or_none((Similarity.productId == sku) & ((Similarity.uprice*1.01) >= price))
            if uprod:
                text = (
                    f"<b>Ozon</b>\n\n"
                    f"<b>Наименование:</b> <a href='{link}'>{name}</a>\n"
                    f"<b>Цена на юнитке</b>: {uprod.uprice}\n<b>Цена на Ozon</b>: {price}"
                )
                # Parameters to be sent with the request
                params = {
                    'chat_id': CHAT_ID,
                    'text': text,
                    'parse_mode': 'HTML'
                }

                # Send the message
                try:
                    response = requests.get(URL, params=params)
                    result = response.json()
                    if result['ok']:
                        print("Message sent successfully.")
                    else:
                        print("Failed to send message:", result['description'])
                except Exception as e:
                    print(f"Failed to send message: {e}")

            
            Product.get_or_none(crawlid)
            item = {}
            item["appid"] = appid
            item["crawlid"] = crawlid
            item["productUrl"] = link
            item["productId"] = sku
            item["price"] = price
            item["name"] = name
            item["imageUrl"] = image
            Product.create(**item)
            exist = ProductDetails.get_or_none(productId = sku)
            if not exist:
                self.parse_product_details(link, appid, crawlid)

        if next_page:
            next_page = parse_qs(next_page['nextPage'])['page'][0]
            self.parse_product_list(url, appid, crawlid, next_page)
            

    def parse_product_details(self, url, appid, crawlid):
        js_data = self.make_req(url=url)
        dets = json.loads(js_data['seo']['script'][0]['innerHTML'])
        desc = dets['description']
        name = dets['name']
        sku = dets['sku']

        js_data = js_data['widgetStates']
        details = {}
        images = []
        brand = ''
        for key, val in js_data.items():
            key = key.split('-')[0]
            val = json.loads(val)
            if key == 'webGallery':
                for img in val['images']:
                    images.append(img['src'])

            elif key == 'webShortCharacteristics':
                for char in val['characteristics']:
                    param_title = ' '.join([x['content'] for x in char['title']['textRs'] if x['type'] == 'text'])
                    param_value = ' '.join([x['text'] for x in char['values']])
                    details[param_title] = param_value

            elif key == 'webBrand':
                brand = val['name']


        item = {}
        item['appid'] = appid
        item['crawlid'] = crawlid
        item["productId"] = sku
        item["productUrl"] = url
        item["imageUrls"] = images
        item["name"] = name
        item["brandName"] = brand
        item["description"] = desc
        item["details"] = details
        ProductDetails.create(**item)


def get_unit_products():
    unit_resp = requests.post('http://92.53.64.89:9011/get_products', json={"key": UNIT_KEY})
    out = []
    for uprod in unit_resp.json():
        if uprod['price'] and uprod['name']:
            uprod['price'] = int(uprod['price'])
            out.append(uprod)

    return out


genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel()
class AISimilar:
    def __init__(self):
        msg = ('Есть список электроники в таком виде:\n'
                '21: iPhone 14 pro max 256GB\n'
                '52: iPhone 14 promax 256GB\n'
                '36: iPhone 14 pro 256GB\n'
                '13: iPhone 14 pro max 128GB\n'
                '85: iPhone 14 pro max 256\n'
                'Образец: iPhone 14 Pro Max 256GB\n'
                'Из списка надо найти те которые '
                'один и тот же вешь с образцом и в ответе '
                'отправить json со списком нумерации '
                'подходящих товаров если они есть как это:\n'
                '[21, 52, 85]')

        self.chat = model.start_chat(history=[
                {"role": "model", "parts": [msg]}
            ])


    def check_products(self, likes, uprod) -> list:
        likes = [f"{x.productId}: {x.name}" for x in likes]
        likes.append(f"Образец: {uprod['name']}")
        response = self.chat.send_message({"role": "user", "parts": likes})
        return json.loads(response)


