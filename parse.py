import json
import time
import requests
from random import choice
from database import Product, ProductDetails, Similarity
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from keys import *


def remove_url_parameter(url, param_to_remove):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    if param_to_remove in query_params:
        del query_params[param_to_remove]
    
    new_query_string = urlencode(query_params, doseq=True)
    new_url = urlunparse(parsed_url._replace(query=new_query_string))
    
    return new_url


class Parser:
    sess = requests.Session()
    def __init__(self) -> None:
        headers = {
            "User-Agent":"PostmanRuntime/7.40.0",
            "Accept":"*/*",
            "Connection":"keep-alive"
        }
        self.sess.headers.update(headers)
        self.update_proxy()

    def update_proxy(self):
        host, port, login, password = choice(proxies).split(':')
        self.sess.proxies = {
            'http': f'http://{login}:{password}@{host}:{port}',
            'https': f'http://{login}:{password}@{host}:{port}'
        }

    def make_req(self, **kwargs):
        try:
            # time.sleep(1)
            resp = self.sess.get("https://www.ozon.ru/api/composer-api.bx/page/json/v2", params=kwargs, timeout=10)
            print('GET->', resp.request.url)
            print(resp.status_code, resp.content[:100])
            return resp.json()
        except requests.exceptions.ConnectTimeout:
            self.update_proxy()


    def parse_product_list(self, url, appid, crawlid, page=1, retry=10):
        if page == 1:
            js_data = self.make_req(url=url)
        else:
            js_data = self.make_req(url=url, page=page)

        js_data = js_data['widgetStates']
        page_data = None
        next_page = {}
        for key in js_data:
            if key.startswith('searchResultsV2'):
                page_data = json.loads(js_data[key])
            
            elif key.startswith('megaPaginator'):
                next_page = json.loads(js_data[key])

        if retry == 0:
            return
        
        elif not page_data:
            return self.parse_product_list(url, appid, crawlid, page=page+1, retry=retry-1)

        if not 'items' in page_data:
            print('No items found')
            return
        
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

            if 'items' in prod['tileImage']:
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

        if page_data:
            return self.parse_product_list(url, appid, crawlid, page=page+1)
            

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


class AISimilar:
    def __init__(self):
        self.api_index = 0
        self.update()


    def update(self):
        self.session = requests.Session()
        host, port, login, password = proxies[self.api_index%len(proxies)].split(':')
        self.session.proxies = {
            'http': f'http://{login}:{password}@{host}:{port}',
            'https': f'http://{login}:{password}@{host}:{port}'
        }
        print(self.session.proxies)


    def check_products(self, likes, uprod) -> list:
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
                'подходящих товаров как это:\n'
                '[21, 52, 85]'
            )

        payload = {
            "contents": [
                {"role": "model", "parts": [{"text": msg}]},
                {"role": "user", "parts": [{"text": f"{x.productId}: {x.name}"} for x in likes]},
                {"role": "user", "parts": [{"text": f"Образец: {uprod['name']}"}]}
            ],
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
            ],
            "generationConfig": {
                "temperature": 0.8,
                "maxOutputTokens": 800,
                "topP": 0.8,
                "topK": 10
            }
        }
        print('Making request using', GOOGLE_API_KEY[self.api_index%len(GOOGLE_API_KEY)])
        resp = self.session.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key=" + GOOGLE_API_KEY[self.api_index%len(GOOGLE_API_KEY)], 
                                 json=payload)
        open('ai.json', 'wb').write(resp.content)
        js_data = json.loads(resp.content)
        output = []
        if 'error' in js_data:
            if js_data['error']['code'] == 429:
                print("Too many requests, waiting 10 seconds...")
                time.sleep(10)
                self.api_index += 1
                self.update()
                # return self.check_products(likes, uprod)
            return []

        for x in js_data['candidates']:
            for text in x['content']['parts']:
                try: output.extend(json.loads(text['text']))
                except json.decoder.JSONDecodeError: return []

        if output:
            print(payload)
            print('\n'*5)
            print(js_data['candidates'])
        return list(set(output))
