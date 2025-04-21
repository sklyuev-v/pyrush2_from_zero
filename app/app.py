from http.server import HTTPServer, BaseHTTPRequestHandler
from loguru import logger
import os
import io
import hashlib
from PIL import Image

SERVER_ADDRESS = ('0.0.0.0', 8000)
LOGFILE_PATH = 'logs'
LOGFILE_NAME = 'app.log'
LOGFORMAT = "[{time: YYYY-MM-DD HH:mm:ss}] | {level} | {message}"
VALID_FILE_FORMATS = ('JPEG', 'GIF', 'PNG')


logger.add(f'{LOGFILE_PATH}/{LOGFILE_NAME}', format=LOGFORMAT)


class ImageHostingHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.post_routes = {
            '/upload/': ImageHostingHandler.post_upload,
        }

        super().__init__(request, client_address, server)

    def post_upload(self):
        content_length = int(self.headers.get('Content-Length'))

        _, ext = os.path.splitext(self.headers.get('Filename'))

        filedata = self.rfile.read(content_length)
        image_raw_data = io.BytesIO(filedata)

        filename = hashlib.file_digest(image_raw_data, 'md5').hexdigest()

        try:
            with Image.open(image_raw_data) as img:
                if img.format in VALID_FILE_FORMATS:
                    img.save(f'images/{filename}.{ext}')
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


def run_server(server_class=HTTPServer, handler_class=ImageHostingHandler):
    httpd = server_class(SERVER_ADDRESS, handler_class)

    try:
        logger.info(
            f'Serving at http://{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}')
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server stopped by Keyboard Interrupt')
        httpd.server_close()


if __name__ == '__main__':
    run_server()
