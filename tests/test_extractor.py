from sacv_tool.extractor import LayoutLine, order_layout_lines, render_layout_text
from sacv_tool.parser import LAYOUT_START_MARKER


def _line(x0: float, y0: float, text: str) -> LayoutLine:
    return LayoutLine(x0=x0, y0=y0, x1=x0 + 190, y1=y0 + 10, text=text)


def test_two_column_order_and_hanging_indent_start_hints():
    lines = [
        _line(45.5, 80, "Alpha, A. (2024). First reference."),
        _line(55.5, 92, "Journal 1, 1-9."),
        _line(45.5, 110, "Beta, B. (2023). Second reference."),
        _line(55.5, 122, "Journal 2, 2-10."),
        _line(306.7, 70, "Gamma, G. (2022). Third reference."),
        _line(316.7, 82, "Journal 3, 3-11."),
        _line(306.7, 100, "Delta, D. (2021). Fourth reference."),
        _line(316.7, 112, "Journal 4, 4-12."),
    ]

    ordered = order_layout_lines(lines, page_width=612, page_height=792)
    rendered = render_layout_text(ordered, page_width=612).splitlines()

    assert rendered[0].startswith(LAYOUT_START_MARKER + "Alpha")
    assert not rendered[1].startswith(LAYOUT_START_MARKER)
    assert rendered[2].startswith(LAYOUT_START_MARKER + "Beta")
    assert rendered[4].startswith(LAYOUT_START_MARKER + "Gamma")
    assert not rendered[5].startswith(LAYOUT_START_MARKER)
    assert rendered[6].startswith(LAYOUT_START_MARKER + "Delta")


def test_continuous_margin_line_numbers_do_not_trigger_two_column_order():
    lines: list[LayoutLine] = []
    references = [
        (472, 80, 90, "REFERENCES"),
        (473, 104, 90, "Fowler, G. A. (2023). First reference."),
        (474, 128, 126, "Journal One, 1(1), 1-9."),
        (475, 152, 90, "Goldman, A. (2026). Fabricated reference."),
        (476, 176, 126, "Imaginary Journal, 2(1), 10-20."),
        (477, 200, 90, "Hevner, A. R. (2004). Third reference."),
    ]
    for number, y0, text_x0, text in references:
        lines.append(LayoutLine(55.5, y0 + 2, 74.9, y0 + 14, str(number)))
        lines.append(LayoutLine(text_x0, y0, 508.0, y0 + 12, text))

    ordered = order_layout_lines(lines, page_width=595.3, page_height=841.9)
    rendered = render_layout_text(ordered, page_width=595.3).splitlines()

    assert all(not line.removeprefix(LAYOUT_START_MARKER).isdigit() for line in rendered)
    assert [line.removeprefix(LAYOUT_START_MARKER) for line in rendered] == [
        text for _number, _y0, _x0, text in references
    ]
    assert rendered[1].startswith(LAYOUT_START_MARKER + "Fowler")
    assert not rendered[2].startswith(LAYOUT_START_MARKER)
    assert rendered[3].startswith(LAYOUT_START_MARKER + "Goldman")
