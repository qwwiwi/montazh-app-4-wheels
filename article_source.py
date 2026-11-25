"""Import a supplied Habr article and its figures before model-driven editing."""
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

ARTICLE = re.compile(r'https://habr\.com/(?:ru|en)/(?:companies/[\w-]+/)?(?:articles|news)/\d+/?')

def article_url(value):
    if not ARTICLE.fullmatch(value):
        raise ValueError('Для автоматического сбора вставьте прямую HTTPS-ссылку на статью Хабра.')
    return value.rstrip('/')+'/'

def prepare_article(folder, url):
    target=folder/'source-material'
    if (target/'source.json').is_file():
        if json.loads((target/'source.json').read_text()).get('source_url')==url:
            return
        raise ValueError('В задании уже есть другой источник.')
    with TemporaryDirectory(dir=folder) as staging:
        bundle=Path(staging)/'material'
        bundle.mkdir()
        try:
            result=subprocess.run(['node',str(Path(__file__).with_name('article_capture.cjs')),article_url(url),str(bundle)],
                                  capture_output=True,timeout=150)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Хабр не успел загрузить статью и иллюстрации.') from exc
        if result.returncode or not (bundle/'source.json').is_file():
            raise ValueError('Не удалось получить снимок статьи Хабра. Проверьте доступность ссылки.')
        bundle.rename(target)
