# Template execution contract

## Reference

- Absolute path: `D:\HCMUS\Ki_1_Nam_4\CDMMT\openguard-kids-project\output\report\23120357_23120049.docx`
- SHA-256: `B9F5290EF8CA4207461D8848CDCB3934D15B173685ED00A182DC2588EAB4C9E4`
- Page pattern: one academic cover followed by a short placeholder body.
- Section count: 1.
- Evidence: `template-style-evidence.json`, OOXML package inventory, paragraph/run inspection and section audit in this directory.
- Rendering status during distillation: the packaged renderer could not start because the bundled dependency set on this host does not include `soffice.exe`. Final visual QA must therefore use Microsoft Word PDF export and Poppler rasterization on this host.

## Page system

- A4 portrait, 8.268 x 11.693 inches.
- Margins: 1 inch on all sides.
- Header distance: 0.492 inch. Footer distance: 0.492 inch.
- One column. No distinct odd/even page layout.
- The cover is the first-page pattern. The final report may enable a distinct first-page footer so the cover remains unnumbered.

## Typography

- The retained cover uses Times New Roman, predominantly 14 pt, with 18 pt for `BÁO CÁO`.
- Cover institution and title lines are bold and centered through the source paragraph geometry.
- Placeholder body uses Times New Roman 14 pt for Heading 1, Heading 2 and body text, with bold headings.
- The report body must continue in Times New Roman and preserve the plain black academic appearance. Heading colors must be black.
- Body paragraphs: justified, approximately 13 pt, 1.3 line spacing, 4-6 pt after, first-line indent about 0.3 inch.
- Captions: centered, 11 pt italic, kept with the following figure where possible.

## Lists and tables

- The source has numbering definitions but no body tables.
- New report tables may be added because the placeholder body has no capacity for the required content. Use light-gray borders, dark-gray header fill, white header text, alternating white/pale-gray body rows and deliberate column widths.
- Lists use Times New Roman 12.5-13 pt with a hanging indent and compact spacing.

## Components and content flow

- Preserve the complete cover block, including the university, faculty, title, supervisor, two students, place/year and the embedded logo/drawing.
- Replace only the placeholder body beginning with `1.Tiêu đề 1`.
- Add a report body containing summary, automatic table of contents, abbreviations, requirements, architecture, implementation, technical analysis, security/privacy, testing, deployment, requirement coverage, limitations, conclusion, contribution placeholder and references.
- Add page numbers in the footer while keeping the cover unnumbered.
- Add source-derived screenshots and diagrams with captions. Image notes may remain only where real Windows or packet-capture evidence must be supplied by the students.

## Slot map

- `word/document.xml` cover paragraphs and drawings before the placeholder body: preserve.
- Placeholder paragraphs `1.Tiêu đề 1` through `2.1. Tiêu đề 2.1`: remove and replace with report content.
- `word/media/image1.png`: preserve; it belongs to the cover.
- Footer: editable to add page numbering. Header remains empty.
- Document settings: editable only to request field updates for the table of contents.

## Package preservation

- Preserve theme, numbering, font table, cover media, relationships and `customXml` unless the document library necessarily rewrites package serialization.
- Required source package parts include `[Content_Types].xml`, `_rels/.rels`, `word/document.xml`, `word/_rels/document.xml.rels`, `word/media/image1.png`, `word/theme/theme1.xml`, `word/settings.xml`, `word/numbering.xml`, `word/styles.xml`, `word/webSettings.xml`, `word/fontTable.xml`, `customXml/*` and `docProps/*`.
- The final output is a working copy at a different path; the reference must remain byte-for-byte unchanged.

## Fidelity gates

- The reference SHA-256 must remain unchanged after authoring.
- The cover's text, logo and overall placement must remain recognizable and unmodified.
- A4 portrait geometry and one-inch margins must remain stable.
- All headings, tables, images, captions, notes and page numbers must render without clipping or overlap.
- The final report must be visually inspected page by page after Word PDF export and Poppler rasterization.
