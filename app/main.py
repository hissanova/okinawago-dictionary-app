from flask import Flask, render_template, session, redirect,url_for, flash
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

app = Flask(__name__)

app.config['SECRET_KEY'] = 'Haisai. Chu-uganbira.'

bootstrap = Bootstrap(app)


class NameForm(FlaskForm):
    word = StringField('見出し語（カタカナ）から検索', validators=[DataRequired()])
    submit = SubmitField('検索')


@app.route('/', methods=['GET', 'POST'])
def index():
    form = NameForm()
    if form.validate_on_submit():
        word = form.word.data
        session['word'] = word
        form.word.data = ''
        return redirect(url_for("search_results", word=word))
    return render_template('index.html', form=form)


@app.route('/search-results/<word>')
def search_results(word):
    return render_template('search-results.html', word=word)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500
