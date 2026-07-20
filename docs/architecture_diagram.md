# Architecture Diagram

```mermaid
graph TB
    User([User]) --> UI[Static Dashboard]
    UI -->|REST| API[FastAPI<br/>src/main.py]
    API --> Chat[Chatbot Orchestrator<br/>src/chatbot.py]
    API --> Val[Valuation API<br/>src/valuation.py]
    Chat --> Intent[Intent Rules + Entity Parser]
    Chat --> Retrieval[Missing Info Retrieval]
    Chat --> Val
    Chat -.optional.-> LLM[OpenAI Answer Rewrite]
    Val --> Store[(SQLite / MongoDB)]
    Retrieval --> Store
    Crawler[Crawler + Parser Jobs] --> Store
    Crawler --> CSV[Processed CSV]
    Config[config/projects.yaml] --> Crawler
    Prompts[prompts/] --> Chat
```

## Runtime Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant A as FastAPI
    participant C as Chatbot
    participant V as Valuation
    participant D as Storage
    participant L as Optional OpenAI

    U->>F: Ask valuation/trend question
    F->>A: POST /chat
    A->>C: Validate and route intent
    C->>V: Estimate when enough fields exist
    V->>D: Load comparable listings and snapshots
    D-->>V: Market rows
    V-->>C: P10/P50/P90 + comps
    C-->>L: Grounded context when enabled
    L-->>C: Natural-language rewrite
    C-->>A: ChatResponse
    A-->>F: JSON
    F-->>U: Render answer, chart, comps
```

## Component Summary

| Component | Path | Purpose |
|-----------|------|---------|
| API | `src/main.py` | FastAPI app, CORS, routes |
| Chatbot | `src/chatbot.py` | Intent detection, slot extraction, response orchestration |
| Valuation | `src/valuation.py` | Comparable filtering and weighted quantile estimates |
| Storage | `src/storage.py` | SQLite/MongoDB abstraction |
| Crawler | `src/crawler.py`, `scripts/crawl.py` | Fetch and normalize public market data |
| Parser | `src/parser.py` | Extract listings, price snapshots and candidates |
| Frontend | `frontend/` | Browser dashboard for demo workflows |
