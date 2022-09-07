from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return "<h1>沖縄語辞典</h1>"
