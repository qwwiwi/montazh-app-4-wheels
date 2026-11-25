"""Brand logos follow the cut transcript and live inside its measured captions."""
import json
from pathlib import Path
import re

import pytest

from conftest import build_example

ITEM = {"id":"claude","name":"Север Карта","file":"claude.svg","start":1.5,"end":2.0,
        "word_start":4,"word_end":5,"spoken":"Север Карта,"}
MARK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 25 15"><path fill="#df7221" d="M0 0h25v15H0z"/></svg>'


def build(tmp: Path, item: dict, mark: bytes=MARK):
    (tmp/"mentions.json").write_text(json.dumps({"mentions":[item]}))
    return build_example(tmp, edit_config=lambda cfg:cfg.update(brand_mentions="mentions.json"),
                         assets={"claude.svg":mark})


def test_timed_local_mark_is_inside_the_measured_caption(tmp_path):
    project=build(tmp_path, ITEM).project
    files=list((project/"assets/brands").glob("*.svg"))
    assert len(files)==1 and files[0].read_bytes()==MARK
    page=(project/"index.html").read_text()
    chips=re.findall(r'<img id="([^"]+)" class="brand-chip"[^>]*>',page)
    assert chips
    assert f'tl.set("#{chips[0]}", {{visibility:"visible"}}, 1.5)' in page
    assert f'tl.set("#{chips[-1]}", {{visibility:"hidden"}}, 2)' in page
    for ident in chips:
        assert re.search(r'<span id="[^"]+" class="w[^"]*"><img id="'+ident+r'"',page)
    assert 'object-fit:contain' in page


@pytest.mark.parametrize("change", [{"start":1.6},{"spoken":"Different name"},{"word_end":3},{"file":"../mark.svg"}])
def test_stale_cut_or_escaped_asset_fails(tmp_path,change):
    with pytest.raises(ValueError):
        build(tmp_path, dict(ITEM,**change))


def test_active_svg_fails(tmp_path):
    with pytest.raises(ValueError):
        build(tmp_path,ITEM,mark=b'<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>')
