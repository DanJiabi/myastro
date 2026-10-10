"""设计守卫：注册表漂移、文档同步、边界规则、schema/描述符契约。

（测试分层重组迁移；断言未改动。）
"""
import pytest


@pytest.mark.cap("design.guards")
def test_design_doc_matrix_matches_generator():
    """文档标记块与生成器输出逐字一致（手改文档即红）。"""
    from myastro.io.docsync import BEGIN, DOC, END, render_matrix

    text = DOC.read_text()
    _head, rest = text.split(BEGIN, 1)
    _, _tail = rest.split(END, 1)
    current = text.split(BEGIN)[1].split(END)[0].strip()
    assert current == render_matrix()
