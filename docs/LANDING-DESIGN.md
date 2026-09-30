# Landing page design review

The first stage of the Match Point redesign changes only the public landing page. Open `/` while signed out; signed-in users retain the existing redirect to their workspace. Registration remains the existing shared form with role selection.

## Implementation

- `templates/skillmatch/landing.html` retains Django inheritance and named route links. `base.html` adds optional header, footer, head, favicon and body-class blocks; their original defaults remain in place for other pages.
- `static/css/landing.css` contains the brand tokens and reusable `sm-` components. Login and signup also reuse these styles in the next stage of the rollout; their layout rules are isolated in `static/css/auth.css`. Semantic surface tokens include a foundation for a future dark theme; no theme toggle is exposed.
- `static/js/landing.js` closes the native mobile menu after navigation or Escape. The menu works without JavaScript.
- Fonts and images are served locally. No runtime font or stock-photo services are required. Bootstrap remains the existing local version.
- The profile, fictional Nairobi Works SME and 92% score are presentation examples, not database records or calculated recommendations. The smaller match card retains its illustrative-score label and explains the shared Python/Django skills. The separate image caption was removed in the requested refinement. There are no verification badges, unsupported component scores or new account features.
- The existing “How it works” section uses two compact three-step flows for job seekers and employers. Both stay visible without tabs or additional JavaScript. Navigation and CTA destinations remain unchanged.
- Database models, data, forms, views, URL patterns, matching, authentication and permissions are unchanged.

## Asset provenance

`static/images/brand/match-point.svg` is a scalable vector reproduction of the supplied **brandlogo source of truth.png** mark, preserving the two curved paths, abstract S and central gold point. The horizontal lockup combines it with the Playfair Display wordmark. The same mark is the landing favicon.

Inter and Playfair Display are self-hosted from Google Fonts. Their SIL Open Font Licenses are included in `static/fonts/`. Sources: https://fonts.google.com/specimen/Inter and https://fonts.google.com/specimen/Playfair+Display.

The two editorial images were created using the built-in image-generation tool with `landing visual target.png` as the reference. They depict illustrative people and scenery, not actual platform members. Original PNGs remain in the local generated-image library; JPEG delivery versions retain full dimensions at quality 85, totalling approximately 525 KB.

### Professional hero

Saved asset: `static/images/landing-professional.jpg` (1536 × 1024). Mode: reference-image edit, built-in image tool, one image. Prompt:

> Use case: precise-object-edit. Asset type: website hero editorial photograph. Input image: provided SkillMatch landing visual target is the visual reference. Produce ONLY the clean photographic right-half hero artwork, full bleed in a landscape 3:2 image, NOT an entire webpage. Preserve the reference's young Kenyan professional woman with braided updo, emerald blazer over ivory top, gold earrings, looking thoughtfully at her silver laptop, warm modern Nairobi office, plants and natural light, green mug on pale wood desk. Center the woman around 58% of the frame, show her upper body, laptop and desk, leave some office space at left for separately coded floating cards. Remove ALL UI cards, all navigation, all text, words, numbers, branding, icons, buttons, banners, and skyline inset. No text even in wall artwork. Keep natural realistic editorial photography matching the reference's lighting, colors and character. Image only; no layout mockup. Save the generated asset locally and return its path.

### Nairobi scene

Saved asset: `static/images/landing-nairobi.jpg` (2062 × 763). Mode: reference-image edit, built-in image tool, one image. Prompt:

> Create a clean standalone landscape editorial photograph of the Nairobi skyline as shown in the bottom right of the supplied visual reference: prominent KICC tower, Nairobi buildings, lush green trees foreground, warm late afternoon light and soft blue sky. Wide panoramic composition. No people, text, lettering, logos, UI, frames or overlays. This is an atmospheric website image, not a webpage. Save locally and return the file path.

## Validation

The project validation command passes, including all 40 existing tests, dependency checks, formatting, Django checks, migration drift, production settings checks and static collection. Browser review covers 320, 390, 768, 1024, 1440 and 1672 px widths, image loading, horizontal overflow, named-route links, anchor targets and keyboard mobile navigation. Local review captures are in ignored `tmp/landing-review/`.

The landing-page refinements were approved before work began on login and signup. Further page redesigns await authentication-page approval.
