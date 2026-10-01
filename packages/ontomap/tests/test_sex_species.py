from ontomap import sex, species


def test_female_and_male():
    assert sex.resolve("female").term_id == "PATO:0000383"
    assert sex.resolve("M").term_id == "PATO:0000384"


def test_a_value_naming_both_sexes_maps_to_no_term_but_is_not_absent():
    """One row cannot have two sexes, and 'mixed' must not look like 'missing'.

    A blocker reading the mapped field sees an empty value for exactly the
    pooled rows that most need blocking. Twelve rows were once wrongly
    sex-specialised for this reason, so mixedness is a flag of its own.
    """
    for text in ("female, male", "male and female", "mixed", "both"):
        match = sex.resolve(text)
        assert match.term_id is None
        assert "sex_mixed" in match.flags


def test_absent_is_distinguishable_from_mixed():
    match = sex.resolve("")
    assert match.term_id is None
    assert "sex_mixed" not in match.flags


def test_human_only_and_anything_else_says_so():
    assert species.resolve("Homo sapiens").term_id == "NCBITaxon:9606"
    other = species.resolve("Mus musculus")
    assert other.term_id is None
    assert "non_human" in other.flags
