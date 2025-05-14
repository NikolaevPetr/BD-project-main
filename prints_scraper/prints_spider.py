import scrapy
import requests
import json
from PIL import Image
from io import BytesIO
import os

class PrintsSpider(scrapy.Spider):
    name = 'prints_spider'
    api_key = 'Sut1Kxf2NeGeo4OkHaGApOgPZ-JyCqq3xIoZYdOTA7U'
    start_urls = [f'https://api.unsplash.com/photos/random?count=10&client_id={api_key}']

    # Указываем путь к папке для сохранения изображений
    folder_path = r'C:\Users\user\Desktop\BD\static\prints'

    def parse(self, response):
        data = json.loads(response.body)

        # Создаем папку, если её нет
        if not os.path.exists(self.folder_path):
            os.makedirs(self.folder_path)

        for i, photo in enumerate(data):
            image_url = photo['urls']['regular']

            # Загрузка изображения
            response = requests.get(image_url)
            image_data = BytesIO(response.content)

            # Открытие изображения с использованием библиотеки Pillow
            img = Image.open(image_data)

            # Сохранение изображения в формате PNG и с измененным названием файла
            image_path = os.path.join(self.folder_path, f"image_{101 + i}.png")
            img.convert('RGBA').save(image_path, format='PNG')

            yield {
                'image_url': image_url,
                'description': photo.get('description', ''),
                'image_path': image_path,
            }
# scrapy runspider prints_spider.py