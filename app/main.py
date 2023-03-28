import os
from flask import Flask, render_template, session, redirect, url_for
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from wtforms import widgets, StringField, SubmitField, RadioField, SelectMultipleField
from wtforms.validators import DataRequired

from app.search import search, get_contents

app = Flask(__name__)

app.config['SECRET_KEY'] = 'Haisai. Chu-uganbira.'

bootstrap = Bootstrap(app)


class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


dict_list = [
    ('oki2yamato', '沖→日'),
    ('katsuyou_jiten', 'うちなーぐち活用辞典'),
    ('yamato2oki', '日→沖'),
]

search_types = [
    ('contains', '検索語を含む'),
    ('startswith', '前方一致'),
    ('endswith', '後方一致'),
]


class EnquiryForm(FlaskForm):
    word = StringField('検索語の入力（かな表記）',
                       validators=[DataRequired()],
                       render_kw={
                           "placeholder": "検索語を入力して下さい",
                           "style": "width:100%"
                       })
    dict_type = MultiCheckboxField(
        '検索する辞書の選択',
        choices=dict_list,
        default=[dict_label[0] for dict_label in dict_list])
    search_type = RadioField('検索語と見出し語の一致条件の選択',
                             choices=search_types,
                             default='contains')
    submit = SubmitField('検索')


@app.route('/', methods=['GET', 'POST'])
def index():
    enquiry_form = EnquiryForm()
    if enquiry_form.is_submitted():
        session['search_type'] = enquiry_form.search_type.data
        enquiry_form.search_type.data = ''
        session['dict_type'] = enquiry_form.dict_type.data
        session['word'] = enquiry_form.word.data
        enquiry_form.word.data = ''
        return redirect(url_for("search_results", word=session['word']))
    return render_template('index.html', enquiry_form=enquiry_form)


@app.route('/search-results/<word>')
def search_results(word):
    results = search(
        word,
        session["search_type"],
        session['dict_type'],
    )
    return render_template('search-results.html',
                           word=word,
                           results=results,
                           search_type=session['search_type'],
                           dict_type=session['dict_type'])


@app.route('/definition/<dict_type>/<index_word>')
def definition(dict_type, index_word):
    contents = get_contents(index_word, dict_type)
    return render_template(f'definition-{dict_type}.html',
                           word=index_word,
                           contents=contents,
                           dict_type=dict_type)


@app.route('/about')
def about():
    return render_template('about.html')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
