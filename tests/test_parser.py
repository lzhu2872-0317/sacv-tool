from sacv_tool.parser import parse_citation, parse_reference_pages, parse_references


REFERENCE = (
    "Hendricks, G., Tkaczyk, D., Lin, J., & Feeney, P. (2020). "
    "Crossref: The sustainable source of community-owned scholarly metadata. "
    "Quantitative Science Studies, 1(1), 414-427. https://doi.org/10.1162/qss_a_00022"
)


def test_parse_apa_reference():
    citation = parse_citation(REFERENCE)
    assert citation.year == 2020
    assert citation.doi == "10.1162/qss_a_00022"
    assert citation.title.startswith("Crossref: The sustainable")
    assert citation.authors[0].startswith("Hendricks")
    assert len(citation.authors) == 4


def test_parse_reference_section_and_wrapped_lines():
    text = f"Introduction\nNot a citation.\nREFERENCES\n\n{REFERENCE}\n\nTan, K. L., & Ahmad, S. (2024). Fake paper title. Fake Journal, 1(1), 1-2."
    citations = parse_references(text)
    assert len(citations) == 2
    assert citations[0].ordinal == 1
    assert citations[1].title == "Fake paper title"


def test_repairs_split_reference_splits_merged_reference_and_stops_at_appendix():
    text = """REFERENCES
Buhalis, D., & Leung, R. (2018). Smart hospitality—Interconnectivity and interoperability towards an ecosystem. International Journal of Hospitality
Management, 71, 41–50. https://doi.org/10.1016/j.ijhm.2017.11.011
Qiu, H., Li, M., Shu, B., & Bai, B. (2020). Enhancing hospitality experience with service robots. Journal of Hospitality Marketing & Management, 29(3), 247–268. https://doi.org/10.1080/19368623.2019.1645073 Roberts, C., Edwards, D. V., Hosseini, M. R., Mateo-Garcia, M., & Owusu-Manu, D. (2019). Post-occupancy evaluation: A review of literature. Engineering, Construction and Architectural Management, 26(9), 2084–2106. https://doi.org/10.1108/ECAM-09-2018-0390
Appendix A: Questionnaire
This must never become part of a citation (2025).
"""
    citations = parse_references(text)
    assert len(citations) == 3
    assert citations[0].doi == "10.1016/j.ijhm.2017.11.011"
    assert "International Journal of Hospitality Management" in citations[0].raw
    assert citations[1].doi == "10.1080/19368623.2019.1645073"
    assert citations[2].doi == "10.1108/ecam-09-2018-0390"
    assert all("Questionnaire" not in citation.raw for citation in citations)
    assert "MERGED_CITATION_REPAIRED" in citations[1].parse_flags


def test_page_aware_parser_preserves_real_start_and_end_pages():
    citations = parse_reference_pages(
        [
            (147, "REFERENCES\nBuhalis, D., & Leung, R. (2018). Smart hospitality. International Journal of Hospitality"),
            (148, "Management, 71, 41–50. https://doi.org/10.1016/j.ijhm.2017.11.011\nTan, K. L., & Ahmad, S. (2024). Another complete title. Journal Name, 1(1), 1–2."),
            (149, "APPENDIX A\nQuestionnaire content (2025)."),
        ]
    )
    assert len(citations) == 2
    assert citations[0].source_page == 147
    assert citations[0].source_end_page == 148
    assert citations[1].source_page == 148
    assert citations[1].source_end_page == 148


def test_page_break_continuation_at_left_margin_is_not_a_new_reference():
    marker = "\u241e"
    citations = parse_reference_pages(
        [
            (147, f"REFERENCES\n{marker}Chen, S. (2025). A complete title. Architecture, (6), 117–"),
            (
                148,
                f"{marker}119.\n{marker}Choi, Y. (2020). A separate complete title. Journal Name, 1(1), 1–9.",
            ),
        ]
    )
    assert len(citations) == 2
    assert citations[0].raw.endswith("117– 119.")
    assert citations[0].source_end_page == 148
    assert citations[1].raw.startswith("Choi")


def test_standalone_venue_fragment_is_a_parse_error_candidate():
    citation = parse_citation("Management, 97, Article 102997. https://doi.org/10.1016/j.ijhm.2021.102997")
    assert "SPLIT_CITATION" in citation.parse_flags


def test_title_led_report_with_year_and_doi_is_not_a_fragment():
    citation = parse_citation(
        "2021 China commercial service robot market research report. (2022). "
        "Robot Industry, (2), 76–90. https://doi.org/10.19609/j.cnki.cn10-1324/tp.2022.02.010"
    )
    assert "SPLIT_CITATION" not in citation.parse_flags
    assert citation.year == 2022
    assert citation.authors == []
    assert citation.title == "2021 China commercial service robot market research report"
    assert citation.venue == "Robot Industry"


def test_chicago_naked_year_does_not_split_author_from_title():
    text = (
        "REFERENCES\n"
        "Alkaissi, H., and S. I. McFarlane. 2023. Artificial Hallucinations in ChatGPT: "
        "Implications in Scientific Writing. Cureus 15(2): e35179. "
        "https://doi.org/10.7759/cureus.35179"
    )
    citations = parse_references(text)
    assert len(citations) == 1
    assert citations[0].raw.startswith("Alkaissi")
    assert citations[0].year == 2023
    assert citations[0].doi == "10.7759/cureus.35179"


def test_chicago_final_coauthor_is_not_mistaken_for_next_reference():
    text = (
        "REFERENCES\n"
        "Alaqlobi, O., A. Alduais, F. Qasem, and M. Alasmari. 2024a. "
        "A SWOT analysis of generative AI. F1000Research 13: 1040. "
        "https://doi.org/10.12688/f1000research.155378.1"
    )
    citations = parse_references(text)
    assert len(citations) == 1
    assert citations[0].raw.startswith("Alaqlobi")
    assert "M. Alasmari" in citations[0].raw


def test_chicago_quoted_title_is_separated_from_venue_and_internal_commas():
    citation = parse_citation(
        "Eldakar, M. A. M., A. M. K. Shehata, and A. S. A. Ammar. 2025. "
        "“What motivates academics in Egypt toward generative AI tools? An integrated model "
        "of TAM, SCT, UTAUT2, perceived ethics, and academic integrity.” "
        "Information Development 41(3): 747–65. https://doi.org/10.1177/02666669251314859"
    )
    assert citation.title == (
        "What motivates academics in Egypt toward generative AI tools? An integrated model "
        "of TAM, SCT, UTAUT2, perceived ethics, and academic integrity"
    )
    assert citation.venue == "Information Development"
    assert citation.primary_author.startswith("Eldakar")


def test_chicago_single_author_is_not_parsed_as_title():
    citation = parse_citation(
        "Bennett, L. 2023. “Optimising the Interface between Artificial Intelligence and Human "
        "Intelligence in Higher Education.” International Journal of Teaching, Learning and "
        "Education 2(3): 12–25. https://doi.org/10.22161/ijtle.2.3.3"
    )
    assert citation.primary_author == "Bennett, L"
    assert citation.title.startswith("Optimising the Interface")
    assert citation.venue == "International Journal of Teaching, Learning and Education"


def test_pdf_wrap_hyphen_before_uppercase_is_repaired():
    citation = parse_citation(
        "Cotton, D. R. E. 2024. “Chatting and cheating: Ensuring academic integrity in the era "
        "of Chat- GPT.” Innovations in Education and Teaching International 61(2): 228–39. "
        "https://doi.org/10.1080/14703297.2023.2190148"
    )
    assert "ChatGPT" in citation.title


def test_unquoted_arxiv_title_is_separated_from_container():
    citation = parse_citation(
        "Belcak, P., L. A. Lanzendörfer, and R. Wattenhofer. 2023. Examining the Emergence of "
        "Deductive Reasoning in Generative Language Models. arXiv preprint arXiv:2306.01009, "
        "https://doi.org/10.48550/arXiv.2306.01009"
    )
    assert citation.title == "Examining the Emergence of Deductive Reasoning in Generative Language Models"
    assert citation.venue.startswith("arXiv preprint")


def test_corporate_authors_and_no_date_entries_start_new_references():
    text = """REFERENCES
Smith, J. (2024). A conventional reference with enough metadata. Journal Name, 1(1), 1–2.
Canary Technologies. (n.d.). Hospitality research: Navigating AI. https://resources.example/research.html
H World Group Limited. (2025, May 15). First-quarter financial results. https://example.com/news- releases/details
LeadLeo. (2022). Research report on digital operation and management of Chinese hotels. https://example.com/report.pdf
Sihan Industry Research Institute. (2025, March 23). Market size and future trends. https://example.com/market
Simio. (n.d.). Integrating simulation and digital twin technology in hospitality. https://example.com/digital-twin
UdiTech Robotics. (n.d.). A success story from Huazhu Group. https://example.com/success
Appendix A: Questionnaire
Survey content (2025).
"""
    citations = parse_references(text)
    assert len(citations) == 7
    assert [citation.primary_author for citation in citations[1:]] == [
        "Canary Technologies",
        "H World Group Limited",
        "LeadLeo",
        "Sihan Industry Research Institute",
        "Simio",
        "UdiTech Robotics",
    ]
    assert citations[1].year is None
    assert citations[2].year == 2025
    assert citations[2].title == "First-quarter financial results"


def test_appendix_heading_embedded_in_pdf_block_is_removed():
    text = (
        "REFERENCES\n"
        "Zhu, X. Y., & Peng, Y. W. (2025). Construction of a digital management model. "
        "Shanghai Real Estate, (2), 26–29. https://doi.org/10.13997/example.2025.02.007 "
        "142 Appendix A: Questionnaire Survey content that must be excluded (2025)."
    )
    citations = parse_references(text)
    assert len(citations) == 1
    assert citations[0].doi == "10.13997/example.2025.02.007"
    assert "Appendix" not in citations[0].raw
    assert "APPENDIX_CONTAMINATION" not in citations[0].parse_flags
