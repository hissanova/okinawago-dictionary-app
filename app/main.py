from flask import Flask, render_template, session, redirect, url_for
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, RadioField
from wtforms.validators import DataRequired

from app.search import search, get_contents


app = Flask(__name__)

app.config['SECRET_KEY'] = 'Haisai. Chu-uganbira.'

bootstrap = Bootstrap(app)


class EnquiryForm(FlaskForm):
    word = StringField('見出し語（カタカナ）から検索', validators=[DataRequired()])
    search_type = RadioField('検索方法', choices=[('startswith', '前方一致'), ('endswith', '後方一致')], default='startswith')
    submit = SubmitField('検索')


@app.route('/', methods=['GET', 'POST'])
def index():
    form = EnquiryForm()
    if form.validate_on_submit():
        word = form.word.data
        form.word.data = ''
        search_type = form.search_type.data
        form.search_type.data = ''
        session['word'] = word
        session['search_type'] = search_type
        return redirect(url_for("search_results", word=word))
    return render_template('index.html', form=form)


@app.route('/search-results/<word>')
def search_results(word):
    results = sorted(search(word, session["search_type"]))
    return render_template('search-results.html',
                           word=word,
                           results=results,
                           search_type=session['search_type'])


@app.route('/definition/<index_word>')
def definition(index_word):
    contents = get_contents(index_word)
    return render_template('definition.html', word=index_word, contents=contents)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500
