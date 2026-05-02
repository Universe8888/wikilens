# P6 Judge Borderline Decisions

Decisions where any axis scored 3 (borderline zone). Reviewed after each eval run to assess rubric quality.

## 2026-05-01 16:31:30 (0eab57a) — 7 borderline decision(s)

### gap_id: `calvin-cycle`
- **Question:** What is the Calvin cycle and how does it use the ATP and NADPH produced by the light reactions to fix carbon dioxide into organic molecules?
- **Scores:** faithfulness=5 coverage=3 attribution_quality=4 stub_structure=5
- **Rationale:** All claims in 'What the vault says' are supported by cited chunks.|The stub covers most key claims but misses specific details on RuBisCO, phases of the cycle, and production of G3P.|Citations point to appropriate evidence; however, they could better emphasize RuBisCO's role and cycle phases.|Structure is correct with all sections present and ordered.

### gap_id: `peace-of-westphalia-terms`
- **Question:** What were the specific territorial and religious terms of the Peace of Westphalia, and how did they redraw the map of Europe in 1648?
- **Scores:** faithfulness=4 coverage=2 attribution_quality=3 stub_structure=5
- **Rationale:** faith|The stub is mostly faithful, but lacks coverage of specific details on territorial and religious terms mentioned in the gold key claims.|cov|While it correctly identifies the general scope of the Peace of Westphalia, it misses most of the specific territorial and religious details required by the key claims, such as particular acquisitions and recognitions of sovereignty.|attr|Citations are appropriate but fail to point out specifics due to the unavailability of detailed content in the provided chunks.|struct|The stub is well-structured with all sections present and in order.

### gap_id: `photosystem-mechanisms`
- **Question:** What are the specific roles of Photosystem I and Photosystem II in the light reactions, and how do they work together to transfer electrons and produce ATP and NADPH?
- **Scores:** faithfulness=3 coverage=3 attribution_quality=3 stub_structure=5
- **Rationale:** Some sentences make claims the cited chunk does not support, such as the specifics of electron transport chain roles.|Several key claims partially addressed or omitted, such as photolysis details and the Z-scheme.|Citations present but some point at loosely-related chunks, lacking specificity for processes described.|Frontmatter present, all four sections in order, no prose outside sections.

### gap_id: `cast-iron-seasoning`
- **Question:** What is the seasoning process for cast iron pans, why is it necessary, and how should it be maintained?
- **Scores:** faithfulness=2 coverage=2 attribution_quality=3 stub_structure=5
- **Rationale:** The stub's claims about seasoning and heat retention are only partially supported by the cited chunks, and it lacks detail on the temperature and upside-down baking method.|The stub addresses the need for regular seasoning but omits several key claims such as the initial seasoning process, maintenance practices, and carbon steel comparison.|The citations point to some loosely related chunks, particularly regarding stainless steel, which is not directly relevant to the seasoning process.|The stub is correctly structured with the required sections in order and no extraneous prose outside sections.

### gap_id: `reducing-sugars-definition`
- **Question:** What are reducing sugars, which common sugars qualify as reducing sugars, and why are they specifically involved in the Maillard reaction?
- **Scores:** faithfulness=5 coverage=3 attribution_quality=5 stub_structure=5
- **Rationale:** All cited claims in 'What the vault says' are supported by retrieved chunks.|Several key claims about specific types of reducing sugars and their role in the Maillard reaction are not addressed.|Each citation correctly reflects content from the correct chunks, making the citations high quality.|The stub has proper structure with all necessary sections in the correct order.

### gap_id: `wsgi-vs-asgi`
- **Question:** What is the difference between WSGI and ASGI, and why does the ASGI architecture enable asynchronous request handling while WSGI does not?
- **Scores:** faithfulness=4 coverage=4 attribution_quality=3 stub_structure=5
- **Rationale:** The claims about WSGI and ASGI in the stub are generally supported by the cited chunks, though there are minor unsupported nuances regarding ASGI's event loop operations which are less explicit in the chunks.|The stub addresses most gold key claims, but misses explicit mention of ASGI's support for long-lived protocols like WebSockets.|While citations are used, some do not point to the strongest evidence available for claims, particularly regarding ASGI's non-blocking characteristics.|The stub structure is correct with all required sections present and in order.

### gap_id: `fond-and-deglazing`
- **Question:** What is fond (the browned deposits left in a pan after searing), and how is the deglazing technique used to incorporate it into a sauce?
- **Scores:** faithfulness=4 coverage=4 attribution_quality=3 stub_structure=5
- **Rationale:** Faithfulness is mostly high, though the stub mentions deglazing which isn't well supported by cited chunks.|Coverage is good as it touches on most key claims, but lacks detail on the deglazing steps and sauce development.|Attribution Quality could be improved, as some citations are loosely related to the core topics discussed, particularly deglazing.|Stub Structure is perfect, with all sections present and in the correct order.

## 2026-05-01 16:50:52 (0eab57a) — 6 borderline decision(s)

### gap_id: `calvin-cycle`
- **Question:** What is the Calvin cycle and how does it use the ATP and NADPH produced by the light reactions to fix carbon dioxide into organic molecules?
- **Scores:** faithfulness=4 coverage=3 attribution_quality=4 stub_structure=5
- **Rationale:** faith|The stub accurately summarizes the supporting chunks, though the historical detail about Calvin et al. isn't directly supported by the chunks.|cov|Key claims on RuBisCO's role, the three phases, and G3P output are absent from both sections.|attr|Most citations are appropriate and point to relevant evidence, though the historical reference is not covered.|struct|The stub is well-structured with all sections present and in the correct order.

### gap_id: `async-await-python-web`
- **Question:** How does Python's async/await mechanism work, and why does it improve performance for I/O-bound web requests compared to synchronous WSGI frameworks?
- **Scores:** faithfulness=4 coverage=3 attribution_quality=4 stub_structure=5
- **Rationale:** faith|The stub accurately represents the chunks but lacks detailed explanation of the async/await mechanism's implementation and its effect on performance.|cov|The stub covers the distinction between WSGI and ASGI frameworks but misses several gold key claims regarding event loops, CPU-bound work, and synchronous code handling.|attr|Most citations are appropriate and point to relevant chunks, but wider explanatory connections could enhance the attribution quality.|struct|The stub has all required sections in order with no structural issues.

### gap_id: `photosystem-mechanisms`
- **Question:** What are the specific roles of Photosystem I and Photosystem II in the light reactions, and how do they work together to transfer electrons and produce ATP and NADPH?
- **Scores:** faithfulness=3 coverage=3 attribution_quality=3 stub_structure=5
- **Rationale:** Multiple sentences in 'What the vault says' are not fully supported by cited chunks, especially regarding specific PS roles.|The stub fails to explicitly cover nuanced roles of PSII and PSI such as light absorption specifics and distinct electron roles in ATP and NADPH production.|Some citations reference general information that doesn't align strongly with specific details about PS role mechanics.|The stub is well-structured with all necessary sections correctly ordered and formatted.

### gap_id: `cast-iron-seasoning`
- **Question:** What is the seasoning process for cast iron pans, why is it necessary, and how should it be maintained?
- **Scores:** faithfulness=3 coverage=1 attribution_quality=3 stub_structure=5
- **Rationale:** The sections attribute all claims to a single, broad citation which does not provide specific support for each claim.|The stub fails to cover any gold key claim adequately, as it lacks both specific answers and identification of evidence gaps detailed enough to match the claims.|The single citation to chunk `af10a0f2c9e08cb36a4ddddefb8197ab` does not directly align with the notes or instructions needed and is too general.|The stub follows the required structure, with all sections present and correctly formatted.

### gap_id: `django-database-migrations`
- **Question:** What are Django database migrations, how are they created and applied, and how do they keep the database schema synchronized with model changes?
- **Scores:** faithfulness=5 coverage=3 attribution_quality=3 stub_structure=5
- **Rationale:** The stub accurately represents that there is no existing coverage related to the question in the provided chunks.|Only one gold key claim (the lack of information) is explicitly covered through evidence gaps, missing detailed coverage on Django migration process and functionality.|Citations do not point to any chunks with relevant information, indicating a mismatch between the citations and necessary information.|The stub is well-structured with all required sections present and logically ordered.

### gap_id: `wsgi-vs-asgi`
- **Question:** What is the difference between WSGI and ASGI, and why does the ASGI architecture enable asynchronous request handling while WSGI does not?
- **Scores:** faithfulness=4 coverage=4 attribution_quality=3 stub_structure=5
- **Rationale:** The stub claims are mostly supported by the cited chunks, but the link between ASGI and concurrency isn't detailed in the chunks|Most key claims are covered; however, the handling of concurrency through event loops is not fully addressed|Citations generally point to relevant chunks, but some claims lack direct or strong support in the cited chunks|All sections are included and ordered correctly with no extra prose outside the structure.

## 2026-05-01 16:53:42 (0eab57a) — 5 borderline decision(s)

### gap_id: `peace-of-westphalia-terms`
- **Question:** What were the specific territorial and religious terms of the Peace of Westphalia, and how did they redraw the map of Europe in 1648?
- **Scores:** faithfulness=4 coverage=3 attribution_quality=4 stub_structure=5
- **Rationale:** The stub is mostly faithful, but minor nuances like the specifics of territorial claims aren't fully corroborated given the supporting chunks don't detail these.|Coverage is incomplete, with only a few key claims noted in What the vault says and several major claims missing from both sections.|Citations are generally appropriate, mostly pointing to the strongest evidence available, though there are gaps missing stronger citing detail.|The stub is well-structured with no formatting issues, each section is correctly placed and organized.

### gap_id: `spanish-dutch-1648`
- **Question:** What were the specific terms of the 1648 treaty between Spain and the Dutch Republic, and how did Spain formally recognize Dutch independence?
- **Scores:** faithfulness=5 coverage=3 attribution_quality=5 stub_structure=5
- **Rationale:** All statements in 'What the vault says' are supported by the cited chunks.|Only some gold key claims are covered, with recognition of need for more detail in Evidence gaps.|Citations accurately point to relevant chunks, providing support for all statements made.|All structural elements are present with no formatting errors, maintaining proper organization.

### gap_id: `cast-iron-seasoning`
- **Question:** What is the seasoning process for cast iron pans, why is it necessary, and how should it be maintained?
- **Scores:** faithfulness=2 coverage=3 attribution_quality=3 stub_structure=5
- **Rationale:** Most claims about seasoning necessity and heat retention are only partially supported by the cited chunks, as they don't address detailed seasoning processes.|The stub covers some facts about the need for seasoning and heat properties but lacks details on the polymerization process, maintenance specifics, initial seasoning steps, and carbon steel parallel.|The attribution to source `af10a0f2c9e08cb36a4ddddefb8197ab` lacks depth as it doesn't encompass the polymerization or specific care needs of seasoning.|The stub has a clear structure with all required headings present in appropriate order without extraneous content.

### gap_id: `wsgi-vs-asgi`
- **Question:** What is the difference between WSGI and ASGI, and why does the ASGI architecture enable asynchronous request handling while WSGI does not?
- **Scores:** faithfulness=3 coverage=4 attribution_quality=3 stub_structure=5
- **Rationale:** Some statements exceed their supporting chunks, particularly regarding ASGI's asynchronous request handling.|Most key claims are included except the mention of ASGI supporting long-lived protocols, which is missing.|Citations point to potentially related chunks but often do not contain direct evidence for specific claims made.|Structure is well-organized, following the required format with all sections present.

### gap_id: `fond-and-deglazing`
- **Question:** What is fond (the browned deposits left in a pan after searing), and how is the deglazing technique used to incorporate it into a sauce?
- **Scores:** faithfulness=4 coverage=4 attribution_quality=3 stub_structure=5
- **Rationale:** One claim about stainless steel promoting sticking is unsupported|Most key claims covered, but not the scraping process and resulting sauce|Some citations loosely related; chunk [44db35c49df6746c6f9264a516884030] not sufficiently linked|Structure is correct with all sections present and in order.

## 2026-05-01 18:27:23 (0eab57a) — 1 borderline decision(s)

### gap_id: `spanish-dutch-1648`
- **Question:** What were the specific terms of the 1648 treaty between Spain and the Dutch Republic, and how did Spain formally recognize Dutch independence?
- **Scores:** faithfulness=5 coverage=3 attribution_quality=4 stub_structure=5
- **Rationale:** All claims in 'What the vault says' are supported by cited chunks.|The stub fails to cover key claims about Dutch control of territories and retention of overseas conquests.|Citations generally align with the best available evidence, though some could be strengthened with more specific chunks.|The stub is well-structured with all necessary sections present and properly ordered.
