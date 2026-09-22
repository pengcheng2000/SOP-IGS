"""Real Word regression: sample placement, TOC spacing, and photo heading pagination."""
import json
import re
from pathlib import Path
from zipfile import ZipFile

from app.services.docx import (
    DocPhoto,
    DocPhotoGroup,
    GenerationInput,
    generate_docx,
    validate_docx,
)
from app.services.docx.com_finalizer import finalize_with_word
from app.services.docx.toc import number_separator_span
from lxml import etree
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def run():
    import pythoncom
    import win32com.client

    output = ROOT / 'runtime' / 'sample-word-verification'
    output.mkdir(parents=True, exist_ok=True)
    picture = output / 'fixture.jpg'
    Image.new('RGB', (1600, 1000), '#0f766e').save(picture)
    samples = tuple(DocPhotoGroup(key, key, title,
                                  tuple(DocPhoto(f'{key}{n}', picture, f'{title}{n+1}') for n in range(count)),
                                  'fixed_columns', 2, sort_order=i)
                    for i, (key, title, count) in enumerate([
                        ('sample_front_closed','正面关门整体',1),
                        ('sample_front_open','正面开门整体',1),
                        ('sample_diagonal','对角 45°',2)]))
    path = output / 'samples-toc-titles.docx'
    report = generate_docx(ROOT / 'templates/liquid-cooled-cabinet/v1/master.docx', path, GenerationInput(
        project={'name':'样品、目录及分页验证','document_title':'样品、目录及分页验证'},
        selected_test_item_ids=('visual_inspection','alarm_bms'),
        photos_by_test_item={'visual_inspection': (DocPhoto('test', picture, '测试证据'),)},
        sample_photo_groups=samples,
    ))
    report['word'] = finalize_with_word(path)
    report['validation'] = validate_docx(path)
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx('Word.Application')
    word.Visible = False
    word.DisplayAlerts = 0
    document = None
    try:
        document = word.Documents.Open(str(path.resolve()), False, True, False)
        toc = document.TablesOfContents.Item(1).Range.Text
        entries = [line for line in toc.split('\r') if re.match(r'^[ \t]*\d+\.', line)]
        assert entries and any('5.2.1.1.' in entry for entry in entries), entries
        assert all(number_separator_span(entry) is None for entry in entries), entries
        assert all('\t' in entry for entry in entries), 'Missing page-number tab'
        report['toc_entries'] = entries
        for paragraph in document.Paragraphs:
            if paragraph.Range.Text.strip() != '测试照片':
                continue
            title_page = paragraph.Range.Information(3)
            next_range = document.Range(paragraph.Range.End, document.Content.End)
            first_picture = next_range.InlineShapes.Item(1)
            image_page = first_picture.Range.Information(3)
            assert title_page == image_page, (title_page, image_page)
            report['title_page'] = title_page
            report['first_image_page'] = image_page
        assert 'title_page' in report
    finally:
        if document is not None:
            document.Close(0)
        word.Quit()
        pythoncom.CoUninitialize()
    with ZipFile(path) as archive:
        root = etree.fromstring(archive.read('word/document.xml'))
    assert not root.xpath('//w:tbl//w:t[text()="测试照片"]', namespaces=NS)
    blocks = list(root.find('w:body', NS))
    content = lambda node: ''.join(node.xpath('.//w:t/text()', namespaces=NS))
    start = next(i for i, node in enumerate(blocks) if content(node) == '样品照片')
    end = next(i for i, node in enumerate(blocks) if content(node) == '样品尺寸及重量')
    assert sum(len(node.xpath('.//w:drawing', namespaces=NS)) for node in blocks[start:end]) == 4
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'file': str(path), 'toc_entries':len(report['toc_entries']),
                      'sample_photos':4, 'title_page':report['title_page'], 'valid':True}))


if __name__ == '__main__':
    run()
