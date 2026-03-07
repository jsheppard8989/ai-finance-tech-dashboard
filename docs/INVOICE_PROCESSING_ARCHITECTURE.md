# Enterprise Invoice Processing System — Architecture & Process

**Context:** ~8,000 invoices/day from thousands of vendors → auto-extract, persist to DB, track exceptions, learn from manual corrections.

---

## 1. High-Level Flowchart

```mermaid
flowchart TB
    subgraph INGESTION["1. Ingestion"]
        A[Incoming invoices] --> B[Landing zone / queue]
        B --> C[File type detection]
        C --> D[Parse PDF/Image/EDI/Email]
        D --> E[Document chunk / page split]
        E --> F[Stable document ID]
    end

    subgraph EXTRACTION["2. Extraction"]
        F --> G[Vendor recognition / routing]
        G --> H[Model selection by vendor or template]
        H --> I[Structured extraction]
        I --> J[Confidence scores per field]
    end

    subgraph VALIDATION["3. Validation & Enrichment"]
        J --> K[Schema & business rules]
        K --> L{Valid?}
        L -->|Yes| M[Normalize & enrich]
        L -->|No| N[Exception queue]
        M --> O[Dedupe check]
        O --> P[Ready for DB]
    end

    subgraph PERSISTENCE["4. Persistence & Events"]
        P --> Q[Write to DB]
        Q --> R[Audit log / event bus]
        R --> S[Downstream systems / reporting]
    end

    subgraph EXCEPTIONS["5. Exception Handling"]
        N --> T[Exception dashboard]
        T --> U[Manual review / correct]
        U --> V[Save correction to DB]
        V --> W[Feedback pipeline]
    end

    subgraph LEARNING["6. Learning Loop"]
        W --> X[Label store]
        X --> Y[Retrain / fine-tune]
        Y --> Z[Model version & A/B]
        Z --> H
    end

    INGESTION --> EXTRACTION --> VALIDATION --> PERSISTENCE
    VALIDATION --> EXCEPTIONS
    EXCEPTIONS --> LEARNING
```

---

## 2. Step-by-Step Process Description

### Phase 1 — Ingestion

| Step | Description |
|------|-------------|
| **1.1 Incoming invoices** | Invoices arrive via email (mailbox/API), SFTP, API uploads, or scan/print pipelines. Use a single **landing zone** (e.g. blob store + message queue) so every document has one entry point. |
| **1.2 Landing zone / queue** | Write raw files to object storage (e.g. S3/GCS) with a unique ID; publish a message (e.g. Kafka/SQS) with that ID and metadata (source, timestamp). Decouples receipt from processing and allows replay. |
| **1.3 File type detection** | Detect MIME type and format (PDF, image, EDI, XML, etc.). Route to the right parser; reject or quarantine unsupported types. |
| **1.4 Parse** | **PDF:** text extraction (and OCR fallback for scans). **Images:** OCR (Tesseract, cloud vision, or doc AI). **EDI/XML:** schema-based parsing. Output: text + optional layout (regions, tables). |
| **1.5 Chunk / page split** | Split multi-page PDFs into pages or logical sections. Assign a stable **document ID** (and page/section IDs) used everywhere (DB, exceptions, learning). |
| **1.6 Stable document ID** | One canonical ID per invoice (e.g. hash of content + source + timestamp, or vendor ref + number). Used for dedupe, audit, and linking corrections to the right document. |

**Output:** Normalized “document” records (ID, raw path, text/layout, metadata) ready for extraction.

---

### Phase 2 — Extraction

| Step | Description |
|------|-------------|
| **2.1 Vendor recognition / routing** | Identify vendor (template ID or vendor master key). Use: header/footer text, logo, domain from email, or a small classifier. Enables **vendor- or template-specific** models or rules. |
| **2.2 Model selection** | Per vendor/template: choose extraction model (generic vs fine-tuned), rule set, or hybrid. Store mapping in config DB. |
| **2.3 Structured extraction** | Extract fields: invoice number, date, due date, line items (description, qty, unit price, amount), totals, tax, vendor details, PO/contract refs. Use: LLM + structured output, doc AI, or traditional ML + rules. |
| **2.4 Confidence per field** | For each field, output a confidence score (0–1). Low confidence → flag for review or exception. Enables **selective** human-in-the-loop. |

**Output:** Structured payload (e.g. JSON) plus confidence scores; link to document ID.

---

### Phase 3 — Validation & Enrichment

| Step | Description |
|------|-------------|
| **3.1 Schema & business rules** | Validate types (dates, numbers), required fields present, totals match line items, currency consistency. Check against **vendor master** (allowed vendors, payment terms). Flag duplicates (same vendor + invoice number). |
| **3.2 Valid?** | If all rules pass and confidence is above threshold → **Ready for DB**. Otherwise → send to **exception queue** with reason codes (e.g. low_confidence, total_mismatch, unknown_vendor). |
| **3.3 Normalize & enrich** | Normalize dates, currencies, units; resolve vendor ID from master data; attach cost center/GL from rules or lookup. |
| **3.4 Dedupe check** | Query DB (and/or cache) for same vendor + invoice number (and optional document hash). If duplicate → exception or skip; otherwise proceed. |
| **3.5 Ready for DB** | Final payload: document ID, extracted + normalized fields, validation flags, processing timestamp. |

**Output:** Either a “clean” record for persistence or an exception record with reason and payload for review.

---

### Phase 4 — Persistence & Events

| Step | Description |
|------|-------------|
| **4.1 Write to DB** | Write to **invoices** (and related **line_items**) tables; use transactions. Store document ID, raw file path or blob ref, extracted JSON, and status. Optionally version rows for audit. |
| **4.2 Audit log / event bus** | Publish event (e.g. “Invoice.Processed” or “Invoice.Exception”) with IDs and key fields. Enables dashboards, reporting, and downstream systems (AP, analytics) without coupling. |
| **4.3 Downstream** | Downstream systems consume events or query DB: AP workflow, reporting, reconciliation. |

**Output:** Invoice data in DB; events for observability and integration.

---

### Phase 5 — Exception Handling

| Step | Description |
|------|-------------|
| **5.1 Exception dashboard** | UI listing exceptions with filters (reason, vendor, date). Show document preview, extracted values, confidence, and reason code. |
| **5.2 Manual review / correct** | Operator corrects or confirms fields (and can add notes). Actions: Approve as-is, Edit then approve, Reject, or Escalate. |
| **5.3 Save correction to DB** | Persist corrected values to DB; mark invoice status (e.g. approved, rejected); store “corrected” snapshot and who/when. |
| **5.4 Feedback pipeline** | Every correction (original extraction vs human-approved) is written to a **label store** (document ID, field, model version, original value, corrected value, timestamp). This is the dataset for learning. |

**Output:** Exceptions resolved; all corrections logged for model improvement.

---

### Phase 6 — Learning Loop

| Step | Description |
|------|-------------|
| **6.1 Label store** | Append-only store of (document_id, field, model_version, predicted_value, corrected_value). Optionally link to vendor/template. |
| **6.2 Retrain / fine-tune** | Periodically (or on threshold): build training batches from label store; retrain or fine-tune extraction model (e.g. per vendor or per field). Version models (e.g. v1, v2). |
| **6.3 Model version & A/B** | New model is deployed as new version; route a % of traffic (e.g. by vendor or random) to new model. Compare exception rate and correction rate; promote if better. |
| **6.4 Back into extraction** | Promoted model becomes default for the relevant vendor/template in step 2.2. |

**Output:** Models that improve over time from production corrections; fewer exceptions and less manual work.

---

## 3. Supporting Flowcharts

### 3a. Exception Handling Detail

```mermaid
flowchart LR
    A[Exception created] --> B{Reason}
    B -->|Low confidence| C[Review queue]
    B -->|Validation fail| C
    B -->|Duplicate| D[Auto-resolve or flag]
    C --> E[Operator assigns]
    E --> F[View doc + extraction]
    F --> G{Action}
    G -->|Approve| H[Update DB + feedback]
    G -->|Edit| I[Correct fields]
    I --> H
    G -->|Reject| J[Mark rejected + reason]
    G -->|Escalate| K[Expert queue]
    H --> L[Label store]
```

### 3b. Learning Feedback Loop

```mermaid
flowchart TB
    subgraph PRODUCTION
        M[Extraction model vN]
        M --> P[Predictions]
        P --> Q[Corrections in UI]
        Q --> R[(Label store)]
    end

    subgraph TRAINING
        R --> S[Sample / filter]
        S --> T[Train vN+1]
        T --> U[Evaluate on holdout]
        U --> V{Better?}
        V -->|Yes| W[Deploy vN+1]
        V -->|No| X[Keep vN]
        W --> M
    end
```

### 3c. Vendor / Template Routing

```mermaid
flowchart TB
    D[Document] --> V[Vendor recognizer]
    V --> L{Vendor known?}
    L -->|Yes| T[Get template ID]
    L -->|No| G[Generic model]
    T --> C[(Config: template → model)]
    C --> E[Extraction model A/B]
    G --> E
    E --> O[Structured output]
```

---

## 4. How to Start the Process (Practical Order)

1. **Define the data model**  
   Tables: invoices (header + metadata), line_items, documents (raw ref + parsed text), exceptions, label_store. Decide retention and audit requirements.

2. **Stand up ingestion**  
   One landing zone (blob + queue), one document ID strategy, and parsing for your main formats (PDF + OCR). Get “document in → document record out” working first.

3. **Extraction MVP**  
   Start with one vendor or one template; use a single model (e.g. doc AI or LLM with structured output). Emit structured JSON + per-field confidence.

4. **Validation & DB write**  
   Implement schema + business rules and write “valid” extractions to DB; send failures to an exception table with reason codes.

5. **Exception UI**  
   Simple list/detail view: show exception, document preview, extracted vs corrected, and persist corrections to DB and to the label store.

6. **Learning pipeline**  
   Use label store to evaluate and retrain; add model versioning and A/B routing so new models can be rolled out safely.

7. **Scale and harden**  
   Add vendors/templates, tune confidence thresholds, add retries and dead-letter queues, monitoring, and SLAs.

---

## 5. One-Page Visual Summary

```mermaid
flowchart LR
    subgraph IN
        I1[Invoices]
    end

    subgraph CORE
        I1 --> L[Land]
        L --> P[Parse]
        P --> E[Extract]
        E --> V[Validate]
        V --> DB[(DB)]
        V --> EX[Exceptions]
        EX --> UI[Review UI]
        UI --> FB[Feedback]
        FB --> ML[Learn]
        ML --> E
    end

    subgraph OUT
        DB --> AP[AP / Reporting]
    end
```

---

*This document is a conceptual architecture. Implementation choices (cloud, queue, model type, DB) depend on your stack, compliance, and scale.*
