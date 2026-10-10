"""The name joins' SQL, as text — no web framework, so a batch job can import it.

Moved out of `api_common` on 2026-10-10: the classifier imports `SINGLE_BRAND` and `STOREFRONT`, and
it runs in the Airflow image, whose venv carries no fastapi. Importing them from `api_common` (which
imports fastapi for its request helpers) killed every scheduled classify pass with
«ModuleNotFoundError: No module named 'fastapi'» — only the hand-started CLI, in the api image, ever
worked. `api_common` re-exports these, so the API's own imports are unchanged.
"""

# The single-brand join, D77's read rule: a company mapped to **exactly one** brand shows the
# brand; a multi-brand company keeps its registered name, because nothing in either source
# says which of its brands this site is (measured 2026-08-14: the rule patches 334 松山區
# rows and forgoes 17). `having count(distinct brand_name) = 1` is the whole rule.
# **The rule itself, as one fragment, so the two forms below cannot drift apart.** `having
# count(distinct brand_name) = 1` IS D77's read rule; everything around it is plumbing. Two
# spellings of one rule is exactly the shape this repository keeps being bitten by, so the
# load-bearing line exists once and both statements interpolate it.
_SINGLE_BRAND_RULE = "having count(distinct br.brand_name) = 1"

# The per-row form: a correlated subquery for one company name, used where the caller already has a
# handful of rows in hand (the reveal, the classifier's batch, the evaluation sample).
SINGLE_BRAND = (
    "select min(br.brand_name) as brand_name from brand_registration br"
    "  where br.company_name = {company}"
    "  and br.publication_id = ("
    "    select id from brand_publication order by detected_at desc, id desc limit 1)"
    "  " + _SINGLE_BRAND_RULE
)

# **The grouped form — D93's amendment, owner-ruled 2026-08-27 (「採用」).** The same rule computed
# **once** over the whole 288-row table and joined on `company_name`, instead of a `LATERAL`
# re-evaluated per candidate row.
#
# **Why it was worth a ruling rather than a tidy-up.** M8 measured the lateral at **35,533
# executions per keystroke** against a 288-row table — an N+1 written in SQL — and **93% of the
# typeahead's 82,300 buffers**. `reference_place`, the table everyone assumed was the cost, was
# ~1%. The grouped join measured **61× fewer buffers and 5–8× faster, with the result set proved
# identical** (`except all` empty both ways over the whole publication). It changes a query in the
# request path, which is why it was put to the owner with the numbers rather than folded in.
#
# **`min()` is not arbitrary and must stay.** The `having` keeps only companies with exactly one
# distinct brand name, so within a surviving group every row's `brand_name` is that one value and
# `min()` is simply how a grouped query names it. A company with two brands produces **no row**
# here and the join leaves `brand_name` NULL, which is D77's rule: nothing in either source says
# which of its brands a given site is, so it keeps its registered name.
SINGLE_BRAND_GROUPED = (
    "select br.company_name, min(br.brand_name) as brand_name from brand_registration br"
    "  where br.publication_id = ("
    "    select id from brand_publication order by detected_at desc, id desc limit 1)"
    "  group by br.company_name "
    + _SINGLE_BRAND_RULE
)

# The storefront join, D78's read rule: site-level, keyed by the registry number itself, and
# it **outranks the brand join** — the brand says what the company calls its shops, this row
# says what this shop's sign says, which is the only thing that can split a multi-brand
# company's sites. No `having`: the source is one row per site (0014's key enforces it).
STOREFRONT = (
    "select sn.name from storefront_name sn"
    "  where sn.registry_no = {registry}"
    "  and sn.publication_id = ("
    "    select id from storefront_publication order by detected_at desc, id desc limit 1)"
)
