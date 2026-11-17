# **Roopsee – Meta Ads Python Orchestration Plan**

**Goal:** Manually create static image ads, organise them in local folders, and use Python + Meta Marketing API to upload, create, publish and track advertisements.

## **1. Project folder structure**

```
roopsee-meta-ads/
│
├── config/
│   ├── account.json
│   ├── campaigns.json
│   └── adsets.json
│
├── creatives/
│   ├── acne/
│   │   ├── RS_ACNE_001.jpg
│   │   └── RS_ACNE_002.jpg
│   │
│   ├── pigmentation/
│   │   └── RS_PIGMENTATION_001.jpg
│   │
│   ├── trust/
│   │   └── RS_TRUST_001.jpg
│   │
│   └── retargeting/
│       └── RS_RETARGETING_001.jpg
│
├── ads/
│   ├── batch_001.json
│   └── batch_002.json
│
├── data/
│   ├── upload_registry.json
│   ├── ad_registry.json
│   └── performance/
│
├── reports/
│
├── src/
│   ├── validate.py
│   ├── upload_images.py
│   ├── create_campaigns.py
│   ├── create_adsets.py
│   ├── create_creatives.py
│   ├── create_ads.py
│   ├── publish.py
│   ├── fetch_insights.py
│   └── generate_report.py
│
├── .env
├── requirements.txt
└── run.py
```

## **2. Responsibilities of each folder**

| Folder         | Responsibility                                  |
| -------------- | ----------------------------------------------- |
| `config/`      | Meta account, campaign and ad set configuration |
| `creatives/`   | Your manually designed static images            |
| `ads/`         | JSON files defining individual advertisements   |
| `data/`        | Meta IDs, image hashes and upload records       |
| `performance/` | Daily performance snapshots                     |
| `reports/`     | Generated CSV/HTML reports                      |
| `src/`         | Python implementation                           |
| `.env`         | API credentials and environment settings        |

## **3. Image naming convention**

Keep filenames simple:

```
RS_[CATEGORY]_[NUMBER].jpg
```

Examples:

```
RS_ACNE_001.jpg
RS_ACNE_002.jpg
RS_PIGMENTATION_001.jpg
RS_TRUST_001.jpg
RS_RETARGETING_001.jpg
```

Every image gets a unique creative ID.

Keep additional information such as advertising angle, copy and destination in JSON metadata.

## **4. JSON configuration**

You will maintain three configuration levels.

**A. campaigns.json**

Defines the advertising objective and campaign budget.

```
{
  "campaigns": [
    {
      "key": "ROOPSEE_SALES_001",
      "objective": "OUTCOME_SALES",
      "budget_strategy": "CBO",
      "daily_budget": 500,
      "status": "PAUSED"
    }
  ]
}
```

**B. adsets.json**

Defines audience, placements and optimisation.

```
{
  "adsets": [
    {
      "key": "PROSPECTING_001",
      "campaign_key": "ROOPSEE_SALES_001",
      "audience": "BROAD",
      "placements": ["instagram"],
      "optimization_event": "PURCHASE"
    }
  ]
}
```

**C. ads/batch_001.json**

Defines images and their advertising content.

```
{
  "batch_id": "ROOPSEE_BATCH_001",
  "ads": [
    {
      "ad_key": "RS_ACNE_001",
      "adset_key": "PROSPECTING_001",
      "image": "creatives/acne/RS_ACNE_001.jpg",
      "primary_text": "Your skincare routine should fit your needs.",
      "headline": "Know What Your Skin Needs",
      "cta": "LEARN_MORE",
      "destination": "https://roopsee.com/skin-quiz",
      "utm_content": "RS_ACNE_001",
      "status": "DRAFT"
    }
  ]
}
```

## **5. Complete execution workflow**

This is the main operating sequence.

1. **Manual image creation**

   Create static images in Canva, Photoshop or Figma.

   Save them into their respective local folders.
2. **Create JSON batch**

   Add image paths, headlines, primary text, CTA, destination URL and UTM identifiers.
3. **Validate everything**

   Python checks JSON syntax, image existence, unique IDs, file formats and required fields.
4. **Upload images to Meta**

   Use Marketing API to upload each image.

   Meta returns an image hash.
5. **Update upload registry**

   Save local filename, folder, creative ID and Meta image hash.
6. **Create campaigns and ad sets**

   Create them if they don't already exist. Store their Meta IDs.
7. **Create ad creatives**

   Combine uploaded image hashes with advertising copy, headlines and destination URLs.
8. **Create ads**

   Attach creatives to the corresponding ad sets. Initially create ads as PAUSED.
9. **Review and publish**

   Verify image previews, copy, URLs, audience, budget and tracking. Activate only after approval.
10. **Fetch performance**

    Pull daily metrics through Meta Insights API.
11. **Generate reports**

    Compare performance by individual creative and advertising angle.

## **6. Local registry: connecting images with Meta**

Meta won't reproduce your local folder structure.

Your registry maintains the connection.

`data/upload_registry.json`

```
{
  "RS_ACNE_001": {
    "folder": "acne",
    "filename": "RS_ACNE_001.jpg",
    "meta_image_hash": "abc123",
    "uploaded": true
  }
}
```

`data/ad_registry.json`

```
{
  "RS_ACNE_001": {
    "meta_creative_id": "123456",
    "meta_ad_id": "789012",
    "campaign_id": "111",
    "adset_id": "222",
    "status": "PAUSED"
  }
}
```

This is important because you can reuse an uploaded image hash rather than upload the same image repeatedly.

## **7. UTM tracking**

Every individual ad should have its own UTM content identifier.

Example:

```
https://roopsee.com/skin-quiz
?utm_source=instagram
&utm_medium=paid_social
&utm_campaign=roopsee_sales_001
&utm_content=RS_ACNE_001
```

This allows you to identify which creative generated the website visit.

Track performance through two sources:

| Meta Insights API | Website analytics         |
| ----------------- | ------------------------- |
| Impressions       | Sessions                  |
| Reach             | Landing page views        |
| Link clicks       | Quiz completions          |
| CTR               | Add to cart               |
| Spend             | Purchases                 |
| Cost per purchase | Revenue / conversion data |
| ROAS              | Purchase attribution      |

Make sure UTMs persist through the quiz and checkout journey.

## **8. Python commands**

The intended command-line interface:

```
# Validate all files
python run.py validate

# Upload images
python run.py upload --batch batch_001

# Create campaigns and ad sets
python run.py setup --batch batch_001

# Create creatives and paused ads
python run.py prepare --batch batch_001

# Publish approved ads
python run.py publish --batch batch_001

# Fetch yesterday's performance
python run.py insights --date yesterday

# Generate 7-day report
python run.py report --period 7d
```

These commands are the proposed interface to implement, not existing Meta commands.

## **9. Recommended development phases**

I'd implement this in stages rather than building everything together.

| Phase | Work                                 | Deliverable                  |
| ----- | ------------------------------------ | ---------------------------- |
| 1     | Folder structure and JSON schemas    | Input system                 |
| 2     | Validation script                    | Reliable batch validation    |
| 3     | Meta authentication and image upload | Uploaded images              |
| 4     | Campaign and ad set creation         | Meta hierarchy               |
| 5     | Creative and ad creation             | Paused ads                   |
| 6     | UTM tracking and registry            | Ad-level traceability        |
| 7     | Insights API integration             | Performance data             |
| 8     | Reporting                            | Creative performance reports |

## **10. Important engineering rules**

- Never reuse creative IDs.
- Never create duplicate ads when rerunning a batch.
- Keep original batch JSON files unchanged after submission.
- Save all Meta-generated IDs locally.
- Keep sandbox and production credentials separate.
- Use environment variables for API tokens.
- Create ads paused by default.
- Require manual approval before activation.
- Log API errors and support resuming partially completed batches.

## **Final architecture**

**Manual creative production**

Canva / Photoshop / Figma

**Local folders + JSON**

Images · Copy · URLs · Creative IDs

**Python orchestration**

Validation · Upload · Campaigns · Ad sets · Ads

**Meta Marketing API**

Image hashes · Creative IDs · Ad IDs

**Meta Insights + Website Analytics**

UTMs · Purchases · Spend · ROAS

**Creative performance reports**

Identify winners · Plan next batch

**My recommendation:** Start with Phase 1–3. Get the folder structure, JSON validation and Meta image uploading working before implementing campaign creation. This gives you a reliable foundation without prematurely building a complicated system.