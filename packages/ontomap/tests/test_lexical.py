from ontomap import lexical


def test_normalise_drops_qualifiers_and_stopwords():
    assert lexical.normalise("fetal liver tissue") == "liver"
    assert lexical.normalise("region of the thymus") == "thymus"


def test_morphology_map_is_a_map_not_a_stemmer():
    assert lexical.normalise("oesophagus") == "esophagus"
    # A stemmer would collapse these. They are different organs.
    assert lexical.normalise("ureter") != lexical.normalise("urethra")


def test_grouping_classes_are_prefix_matched_not_substring_matched():
    assert lexical.is_grouping_class("subdivision of oviduct")
    assert lexical.is_grouping_class("zone of skin")
    assert lexical.is_grouping_class("skeletal element")
    # Real anatomy that merely contains the word.
    assert not lexical.is_grouping_class("subventricular zone")
    assert not lexical.is_grouping_class("oviduct")


def test_uninformative_uppers():
    assert lexical.is_uninformative("material entity")
    assert lexical.is_uninformative("Organism subdivision")
    assert not lexical.is_uninformative("liver")


def test_split_composite_leaves_single_sites_alone():
    assert lexical.split_composite("uterus, cervix, vagina") == ["uterus", "cervix", "vagina"]
    assert lexical.split_composite("cornea and retina") == ["cornea", "retina"]
    assert lexical.split_composite("upper lobe of left lung") == ["upper lobe of left lung"]
