# Where these marks come from, and on what terms

*Recorded by the evaluator, 2026-09-11, before any of them was drawn with. Nothing here was taken
from a search result or a third-party mirror.*

## AWS — `aws-cloud-logo.svg`, `amazon-ec2.svg`, `amazon-s3.svg`

**Source:** the official **AWS Architecture Icons** package, downloaded 2026-09-11 from
`https://aws.amazon.com/architecture/icons/` — asset
`Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip`, **release 07312026**
(13,988,918 bytes). **The package itself carries no licence file**; the terms are on the page it is
published from and in AWS's trademark guidelines, both read the same day and quoted here.

**The permission, verbatim from the icons page:**

> "We allow customers and partners to use these toolkits and assets to create architecture diagrams."

The page names the acceptable uses as architecture diagrams and materials such as whitepapers,
presentations, data sheets and posters.

**The restrictions, verbatim from `https://aws.amazon.com/trademark-guidelines/`:**

> "You will not misrepresent or embellish your relationship with AWS. You will not display the AWS
> Marks in any manner that implies sponsorship or endorsement by AWS"

> "You will not alter the logo images in any manner, including but not limited to changing the
> proportion, color, or font of the AWS Marks, or adding or removing any elements"

> "You will not incorporate AWS Marks into the names of your organization, products, or services, or
> into your trademarks or logos"

**How this repository stays inside them.** The marks appear in **one architecture diagram of this
project's own deployment**, which is the stated use. **The files are byte-identical to the package's**
— not recoloured, not restyled, not cropped, and placed at their own aspect ratio. Nothing in this
project is named after or branded with an AWS mark, and the diagram makes no claim of endorsement,
sponsorship or partnership. **A mark that needs editing to fit the drawing does not get edited — the
drawing changes.**

## Simple Icons — Cloudflare, FastAPI, PostgreSQL, Apache Airflow, Ollama

Taken from the **Simple Icons 16.28.0** collection already vendored in this repository at
`.claude/skills/archify/brand-marks/`, which is where the other diagrams get them. Simple Icons is
**CC0** — and, as archify's own note says, **that covers the collection work and not the underlying
trademarks**. Same rule as above: referential use in a diagram of our own system, unaltered, no
implication of endorsement.

## nginx — deliberately not a mark

**nginx is drawn as a labelled box, by the owner's instruction.** F5 publishes its own brand
guidelines for the nginx mark and nobody has read them; a box needs no permission. This absence is
recorded rather than left to look like an oversight.

## The standing rule

**A mark this repository does not already hold is never fetched from a web search to fill a gap.**
It is either taken from its owner's own published package after that package's terms have been read
and quoted here, or the thing is drawn as a plain box. Using anything outside its licence forfeits
工程師的素質, whatever it is for.

## GitHub — the Invertocat, from the Simple Icons collection already vendored here

*Recorded by frontend, 2026-10-10, before it was drawn with.*

**The mark:** the Simple Icons 16.28.0 `github` path in `.claude/skills/archify/brand-marks/`
(provenance recorded there: source and guidelines `https://github.com/logos`), unaltered, in its own
colour `#181717`. It appears once, as the label of the GitHub region that holds the public
repository, GitHub Actions and ghcr.io, smaller than the diagram's own title.

**The permission, verbatim from `https://brand.github.com/foundations/logo` (where
`https://github.com/logos` redirects), read 2026-10-10:**

> "Use a permitted GitHub logo to inform others that your project integrates with GitHub."

> "Use the permitted GitHub logos less prominently than your own company or product name or logo."

**The restrictions, verbatim, same page:**

> "Do not use the GitHub name or any GitHub logo in a way that suggests you are GitHub, your offering
> or project is by GitHub, or that GitHub is endorsing you or your offering or project."

> "Do not modify the permitted GitHub logos, including changing the color, dimensions, or combining
> with other words or design elements."

> "The Invertocat and our wordmark should only appear in white, black, or in few cases grey or green."

> "Do not use GitHub trademarks, logos, or artwork without GitHub's prior written permission."

**How this repository stays inside them.** The diagram shows that this project's build runs on
GitHub, which is the permitted «integrates with GitHub» use. The mark is near-black (#181717),
unaltered, not combined with other design elements, and smaller than the project's own title. No
claim of endorsement is made. This use rests on the page's own permission for a «permitted GitHub
logo … to inform others that your project integrates with GitHub»; it does not claim any wider
right, and anything beyond that one use would need GitHub's prior written permission. The mark is
scaled uniformly only (its square 24-unit viewBox drawn at 20 × 20), never stretched, recoloured or
redrawn. GitHub Actions and GitHub Packages (ghcr.io) have no separate mark on
that page, so they stay labelled boxes inside the region.

## Read on 2026-10-10 and NOT adopted — these stay labelled boxes

- **Docker (the whale).** `https://www.docker.com/legal/trademark-guidelines/`: "The Docker's
  registered, unregistered and pending logos, including the Docker "Moby Dock" whale logo … may be
  taken only from Docker's product sheet or from Docker's service screen shot following
  authorization from us." and "Our word Marks (but not logo marks or other graphic depictions of our
  Marks) may be used in an informational context". The logo needs prior authorization, which we do
  not have, so `docker compose` stays words.
- **nginx (F5).** `https://www.f5.com/company/policies/trademarks`: "No right, license or permission
  is granted to use F5's trademarks except as may be provided explicitly by F5, Inc." No explicit
  permission for diagrams was found, so the 2026-09-11 decision stands: a labelled box.
- **Telegram.** `https://core.telegram.org/api/terms`: "You must not use the official Telegram logo
  for your app." and "Both the Telegram brand and its logo are registered trademarks protected by
  law in almost every country." No page granting diagram use was found, so it stays a labelled box.
- **Model Context Protocol.** No brand or logo usage page from its maintainers was found
  (2026-10-10), so the MCP lineage tool stays a labelled box.
- **The dev machine, the GPU box and members' browsers** are generic roles with no vendor mark to
  ask about; they stay labelled boxes.
