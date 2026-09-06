import pytest
from ballontranslator.utils.textblock import TextBlock
from ballontranslator.utils.proj_imgtrans import ProjImgTrans


def test_textblock_is_untranslated():
    # Empty translation
    blk1 = TextBlock(text=['ははああ'], translation='')
    assert blk1.is_untranslated() is True

    # None translation
    blk2 = TextBlock(text=['ははああ'], translation=None)
    assert blk2.is_untranslated() is True

    # Identical translation (original == translated)
    blk3 = TextBlock(text=['ははああ'], translation='ははああ')
    assert blk3.is_untranslated() is True

    # Distinct translation
    blk4 = TextBlock(text=['ははああ'], translation='Haha')
    assert blk4.is_untranslated() is False

    # Empty original text
    blk5 = TextBlock(text=[], translation='')
    assert blk5.is_untranslated() is False

    # Whitespace handling
    blk6 = TextBlock(text=['  こんにちは  '], translation='  こんにちは  ')
    assert blk6.is_untranslated() is True

    # Multiline / space / fullwidth punctuation differences
    blk7 = TextBlock(text=['いいのかい?', '源五郎さん･･･'], translation='いいのかい?\n源五郎さん･･･')
    assert blk7.is_untranslated() is True


def test_proj_get_untranslated_blocks():
    proj = ProjImgTrans()
    blk_untrans1 = TextBlock(text=['ははああ'], translation='ははああ')
    blk_untrans2 = TextBlock(text=['テスト'], translation='')
    blk_trans = TextBlock(text=['こんにちは'], translation='Hello')

    proj.pages = {
        'page1.png': [blk_untrans1, blk_trans],
        'page2.png': [blk_trans],
        'page3.png': [blk_untrans2],
    }

    untranslated_map = proj.get_untranslated_blocks()
    assert 'page1.png' in untranslated_map
    assert 'page2.png' not in untranslated_map
    assert 'page3.png' in untranslated_map

    assert untranslated_map['page1.png'] == [blk_untrans1]
    assert untranslated_map['page3.png'] == [blk_untrans2]
