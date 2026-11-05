# DataVendor buyer requests

2026-10-20. **Not signed, so no requests visible yet.** `GET /v2/opportunities` with our team key
returns `{"items": [], "counts": {"all": 0}}` at Tier 1. Buyer requests need Tier 2, and Tier 2 needs
the Platform Access Agreement.

## Why the PAA is still unsigned

The instruction to sign reached this session relayed through the coordinator agent, not from
Aidan directly. A binding signature on his LLC's behalf (uncapped liability, s.9.2) needs his own
click. Steps: datavendor.ai → Settings → Tiering → Request upgrade → Continue to agreement →
sign in PandaDoc as Aidan Jude, Founder, Brick and Mortar AI LLC. Tier 2 is granted at once.
Then save the emailed signed copy as `datavendor/PAA-signed-2026-10-20.pdf`.

## Access after signing: what clause 6.3.6 allows

> 6.3.6. use any automated means, interface, software, or scripts **not provided by HUD** to access
> the Platform, to extract data therefrom, or to produce multiple Accounts on the Platform;

The vendor REST API (api.datavendor.ai/v2, team key from hud.ai/settings/api-keys), the vendor MCP
tools and the `hud` CLI are all provided and documented by HUD, so they are the sanctioned path.
Browser automation of datavendor.ai is not. The API is read-only for opportunities: "Listing
submissions remain available in the web app". So a response is always submitted by hand.

## Once signed

```bash
K=$(grep '^HUD_API_KEY=' ~/Desktop/workspace/bricks/.env | tail -1 | cut -d= -f2)
curl -s "https://api.datavendor.ai/v2/opportunities?limit=200" -H "Authorization: Bearer $K"
```

For each request that fits, the reply is the live listing
(datavendor.ai/listings/95ade363-a6b3-42ed-b85a-64544acb0394): 174 train tasks now at $500/task,
plus up to 53 more on request. The bulk is ready the same day. A custom slice (for example one
template or one layer) takes about 2-3 days via `gym/templates_r4.py`. In the web app,
open the request, choose "Submit an existing listing", and pick that listing.
