import os
from flask import Flask, send_from_directory

app = Flask(__name__, static_folder='.')

WIZARD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setup_wizard')


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/setup')
def setup():
    return send_from_directory(WIZARD_DIR, 'wizard.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port)
