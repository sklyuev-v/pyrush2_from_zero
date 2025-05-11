from http.server import HTTPServer, BaseHTTPRequestHandler
from loguru import logger
import os
import io
import hashlib
from PIL import Image
import json

import psycopg2
from environs import Env
from urllib.parse import parse_qs

SERVER_ADDRESS = ('0.0.0.0', 8000)
LOGFILE_PATH = 'logs'
LOGFILE_NAME = 'app.log'
LOGFORMAT = "[{time: YYYY-MM-DD HH:mm:ss}] | {level} | {message}"
VALID_FILE_FORMATS = ('JPEG', 'GIF', 'PNG')


logger.add(f'{LOGFILE_PATH}/{LOGFILE_NAME}', format=LOGFORMAT)


class SingletonMeta(type):
    """
    The Singleton class can be implemented in different ways in Python. Some
    possible methods include: base class, decorator, metaclass. We will use the
    metaclass because it is best suited for this purpose.
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Possible changes to the value of the `__init__` argument do not affect
        the returned instance.
        """
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


class DBManager(metaclass=SingletonMeta):
    def __init__(self, dbname, user, password, host, port):
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.conn = self.connect()

    def connect(self):
        try:
            self.conn = psycopg2.connect(
                dbname=self.dbname, user=self.user, password=self.password, host=self.host, port=self.port)
            return self.conn
        except psycopg2.Error as e:
            logger.error(f"DB connection error: {e}")

    def close(self):
        self.conn.close()

    def execute(self, query):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query)
        except psycopg2.Error as e:
            logger.error(f"Error executing query: {e}")

    def execute_file(self, filename):
        try:
            self.execute(open(f'./{filename}').read())
        except FileNotFoundError:
            logger.error(f"File {filename} not found")

    def init_tables(self):
        self.execute_file('init_tables.sql')
        logger.info("Table initialized")
        self.conn.commit()

    def get_images(self, page=1, limit=10):
        offset = (page - 1) * limit
        logger.info(f'Try to get images with offset {offset}')
        with self.connect().cursor() as cursor:
            cursor.execute(
                "SELECT * FROM images ORDER BY upload_time DESC LIMIT %s OFFSET %s", (limit, offset))
            return cursor.fetchall()

    def add_image(self, filename, original_filename, size, ext):
        logger.info(f"Try to add image {filename}")
        with self.conn.cursor() as cursor:
            cursor.execute("INSERT INTO images (filename, original_name, size, file_type) VALUES (%s, %s, %s, %s)",
                           (filename, original_filename, size, ext))
            self.conn.commit()

    def clear_table(self):
        with self.conn.cursor() as cursor:
            cursor.execute("DELETE FROM images")
        self.conn.commit()

    def delete_image(self, filename):
        logger.info(f"Try to delete image from database {filename}")
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM images WHERE filename = %s", (filename,))
            self.conn.commit()
        except psycopg2.Error as e:
            logger.error(f"Error deleting image {e}")


class ImageHostingHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.post_routes = {
            '/upload/': ImageHostingHandler.post_upload,
        }

        self.get_routes = {
            '/api/images/': ImageHostingHandler.get_image_gallery,
            '/api/images-list/': ImageHostingHandler.get_image_list,
        }

        self.delete_routes = {
            '/api/delete/': ImageHostingHandler.delete_image,
        }

        self.db = DBManager()
        super().__init__(request, client_address, server)

    def get_images(self, limit):
        logger.info(f"GET {self.path}")

        query_components = parse_qs(self.headers.get('Query-String'))
        page = int(query_components.get('page', ['1'])[0])

        if page < 1:
            page = 1

        images = self.db.get_images(page, limit)

        images_json = []

        for image in images:
            image = {
                'filename': image[1],
                'original_filename': image[2],
                'size': image[3],
                'upload_date': image[4].strftime('%Y-%m-%d %H:%M:%s'),
                'file_type': image[5]
            }

            images_json.append(image)

        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()

        self.wfile.write(json.dumps({'images': images_json}).encode('utf-8'))

    def get_image_gallery(self):
        self.get_images(limit=9)

    def get_image_list(self):
        self.get_images(limit=10)

    def do_GET(self):
        if self.path in self.get_routes:
            self.get_routes[self.path](self)
        else:
            logger.warning(f'POST 405 {self.path}')
            self.send_response(405, 'Method Not Allowed')

    def post_upload(self):
        content_length = int(self.headers.get('Content-Length'))

        original_filename, ext = os.path.splitext(self.headers.get('Filename'))

        filedata = self.rfile.read(content_length)
        image_raw_data = io.BytesIO(filedata)

        filename = hashlib.file_digest(image_raw_data, 'md5').hexdigest()
        file_size_kb = round(content_length / 1024)

        self.db.add_image(filename, original_filename, file_size_kb, ext)

        try:
            with Image.open(image_raw_data) as img:
                if img.format in VALID_FILE_FORMATS:
                    img.save(f'images/{filename}{ext}')
                    logger.info(f'Succesfull upload - {filename}{ext}')
                else:
                    logger.warning(
                        f'This image type - {img.format} is not allowed')
                    self.send_response(400, 'File type not allowed')
                    return
        except Exception as e:
            self.send_response(400, 'File type is not allowed')
            logger.warning(f'File is not allowed {e}')

        self.send_response(200)
        self.send_header('Location', 'http://localhost/images/')
        self.send_header('Filename', f'{filename}{ext}')
        self.end_headers()

    def do_POST(self):
        if self.path in self.post_routes:
            self.post_routes[self.path](self)
        else:
            logger.warning(f'POST 405 {self.path}')
            self.send_response(405, 'Method Not Allowed')

    def do_DELETE(self):
        delete_fullpath = self.path
        delete_path_chunks = delete_fullpath.partition("/api/delete/")

        if delete_path_chunks[1] in self.delete_routes:
            self.delete_routes[delete_path_chunks[1]](
                self, delete_path_chunks[2])
        else:
            logger.warning(f'POST 405 {self.path}')
            self.send_response(405, 'Method Not Allowed')

    def delete_image(self, image_id):
        logger.info(f'Try to delete image {image_id}')
        filename, ext = os.path.splitext(image_id)
        if not filename:
            logger.warning('Filename header not found')
            self.send_response(404)
            self.end_headers()
            return
        logger.error(filename)
        self.db.delete_image(filename)
        image_fullpath = os.path.join('./images/', f'{filename}{ext}')
        if not os.path.exists(image_fullpath):
            logger.warning(f'Image file {filename}{ext} not found')
            self.send_response(404)
            self.end_headers()
        os.remove(image_fullpath)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Success', 'Image deleted')


def run_server(server_class=HTTPServer, handler_class=ImageHostingHandler):
    httpd = server_class(SERVER_ADDRESS, handler_class)

    env = Env()
    env.read_env()

    db = DBManager(env('POSTGRES_DB'),
                   env('POSTGRES_USER'),
                   env('POSTGRES_PASSWORD'),
                   env('POSTGRES_HOST'),
                   env('POSTGRES_PORT'))

    db.init_tables()

    try:
        logger.info(
            f'Serving at http://{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}')
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server stopped by Keyboard Interrupt')
        httpd.server_close()


if __name__ == '__main__':
    run_server()
