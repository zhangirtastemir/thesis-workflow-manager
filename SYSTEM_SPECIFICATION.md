# COMPLETE SYSTEM ANALYSIS: UniGe CS Master Thesis Management Platform

---

## 0. INVENTORY OF SOURCE MATERIALS

| # | Type | File | Key Content |
|---|------|------|-------------|
| 1 | TXT | `thesisworkflow.txt` | System spec in Russian: roles, entities, workflows, FR codes, UI screens |
| 2 | CSV | `ONGOING3(OngoingThesis).csv` | Live data: ~50+ ongoing thesis records with all fields |
| 3 | PDF | `ThesisProcess- Thesis assignement and development.pdf` (10 slides) | Official process: rounds, bidding, evaluation, thesis abroad, working, end |
| 4 | PDF | `Thesis Process- Final exam...starting from 2023/24.pdf` (9 slides) | New-regime final exam: enrollment, technical exam, committee, marks |
| 5 | PDF | `Thesis Process- Final exam...till 2022/23.pdf` (6 slides) | Old-regime final exam |
| 6 | PDF | `ONGOING3.pdf` (1 page) | Ongoing thesis spreadsheet snapshot (current cohort) |
| 7 | PDF | `ONGOING3-2.pdf` (1 page) | Faculty workload/effort stats (ongoing) |
| 8 | PDF | `ONGOING3-3.pdf` (1 page) | Faculty workload/effort stats (terminated) |
| 9 | PDF | `ONGOING3-4.pdf` (5 pages) | Available proposals Feb 2026 with full abstracts |
| 10 | PDF | `ONGOING3-5.pdf` (16 pages) | Terminated thesis records (historical data) |
| 11 | PNG | `Bidding schedule` screenshot | AulaWeb page showing 5 bidding windows |
| 12 | PNG | `AVAILABLE PROPOSALS: FEBRUARY 2026` screenshot | AulaWeb proposals listing page with navigation |
| 13 | PNG | `Graduation days and committees` screenshot | 4 exam sessions/year, committee composition |
| 14 | PNG | `March 2026 Technical exams committee` screenshot | Per-candidate committees with dates/locations |
| 15 | PNG | `Short guidelines on how to face your Master Thesis` screenshot | Writing guidelines, thesis structure, style |
| 16 | PNG | `ONGOING3.png` | Excel screenshot of ongoing thesis spreadsheet |

---

## 1. UNIFIED SYSTEM SPECIFICATION (SRS Style)

### 1.1 Purpose

The system manages the **complete lifecycle of Master's thesis** at the University of Genoa, Computer Science department: from proposal publication through bidding, assignment, thesis development, review, and final exam.

**[Evidence: thesisworkflow.txt:1-9, ThesisProcess PDF slide 1-2]**

### 1.2 Scope

- 30-credit final dissertation (~6 months of full-time work, ~1/4 of degree)
- 5 bidding rounds per academic year
- ~60-170 active theses at any time, ~30+ faculty supervisors
- Currently managed via AulaWeb (Moodle), Excel spreadsheets, and email

**[Evidence: ThesisProcess PDF slide 2, ONGOING3-2.pdf page 1, ONGOING3-3.pdf page 1]**

### 1.3 Stakeholders

| Stakeholder | Current Tool | Pain Point |
|---|---|---|
| Student | AulaWeb pages, email | Manual bidding via email, no status tracking |
| Supervisor/Professor | Excel (ONGOING3), email | Manual data entry, no automation |
| Reviewer | Email, direct contact | No centralized view of assigned theses |
| Thesis Work Group (Admin) | Excel, email | Conflict resolution, workload balancing done manually |
| Technical Exam Committee | Manual scheduling | Per-candidate committee assembly |

---

## 2. ROLE-PERMISSION MATRIX

**[Evidence: thesisworkflow.txt:15-39, ThesisProcess PDF slides 3-5, 7, Final Exam PDF slides 2-5]**

| Capability | R1: Student | R2: Reviewer | R3: Supervisor/Admin |
|---|---|---|---|
| **PROPOSALS** | | | |
| View published proposals | READ | READ | READ |
| Create/edit proposal | - | - | WRITE |
| Write abstract (<=200 words) | - | - | WRITE |
| Publish/close/archive proposal | - | - | WRITE |
| **BIDDING** | | | |
| View bidding round status | READ | - | READ |
| Submit bids (max 3, ranked) | WRITE (when Open) | - | - |
| Submit "No bidding" | WRITE | - | - |
| Create/start/close round | - | - | WRITE |
| Publish results | - | - | WRITE |
| **ASSIGNMENT** | | | |
| View own assignment | READ | - | READ (all) |
| Assign/unassign/reassign student | - | - | WRITE |
| Refuse assigned thesis | WRITE (triggers re-bid) | - | - |
| **THESIS DEVELOPMENT** | | | |
| View own thesis status | READ | READ (assigned) | READ (all) |
| Submit draft to reviewer (3-month) | WRITE | - | - |
| Leave review/feedback | - | WRITE | - |
| Decide thesis is "terminated" | - | - | WRITE |
| **FINAL EXAM** | | | |
| Submit final exam request | WRITE (40 days before) | - | - |
| Approve final exam request | - | - | WRITE |
| Appoint technical committee | - | - | WRITE (Work Group) |
| Upload final thesis document | WRITE | - | - |
| Approve uploaded document | - | - | WRITE |
| Upload presentation slides | WRITE (2 days before) | - | - |
| Fill exam evaluation form | - | WRITE (committee) | - |
| **ADMIN** | | | |
| Assign reviewers | - | - | WRITE |
| View audit trail | - | - | READ |
| Manual override | - | - | WRITE (logged) |
| Manage faculty workload view | - | - | READ |

**CRITICAL RULE**: The 200-word abstract on the **Proposal** is written by R3 (Professor/Admin), NOT by the student. The student's thesis document also contains an abstract (up to 200 words), but that is a separate artifact.

**[Evidence: thesisworkflow.txt:11,47,87; ThesisProcess PDF slide 8]**

---

## 3. DOMAIN MODEL + RELATIONSHIPS

**[Evidence: thesisworkflow.txt:42-96, ONGOING3 CSV columns, ONGOING3.png]**

```
+---------------+       +------------------+       +---------------+
|   Faculty     |1    * |    Proposal      |       | BiddingRound  |
|---------------|------>|------------------|       |---------------|
| id            |       | id               |*    1 | id            |
| name          |       | title            |------>| name          |
| email         |       | abstract (<=200w)|       | startAt       |
| department    |       | description      |       | endAt         |
| researchGroup |       | supervisorId(FK) |       | status        |
|               |       | addlSupervisorId |       | maxBids(=3)   |
|               |       | tags/primaryTopic|       | rankingMode   |
|               |       | secondaryTopic   |       +-------+-------+
|               |       | isChallenging    |               |
|               |       | isExternal       |               |
|               |       | externalSupervis |               |
|               |       | capacity (typ=1) |               |
|               |       | status(Draft/    |               |
|               |       |  Published/      |               |
|               |       |  Closed/Archived)|               |
|               |       | roundId(FK)      |               |
|               |       | createdAt        |               |
|               |       | updatedAt        |               |
|               |       +--------+---------+               |
|               |                |1                        |
|               |                |                         |
|               |          *     |                    *    |
|               |       +--------+---------+    +----------+------+
|               |       |      Thesis      |    |       Bid      |
|               |       |------------------|    |----------------|
|               |       | id               |    | id             |
|               |  1  * | studentId(FK)    |    | roundId(FK)    |
|               |------>| proposalId(FK)   |    | studentId(FK)  |
|               |       | supervisorId(FK) |    | proposalId(FK) |
|               |       | reviewerId(FK)   |    | rank (1,2,3)   |
|               |       | addlSupId(FK)    |    | type(Bid/NoBid)|
|               |       | startDate        |    | createdAt      |
|               |       | expectedEnd      |    +----------------+
|               |       | isChallenging    |
|               |       | status           |    +----------------+
|               |       | auditLog[]       |    |    Review      |
|               |       +--------+---------+    |----------------|
|               |                |1          *  | id             |
|               |                |------------->| thesisId(FK)   |
|               |                               | reviewerId(FK) |
+---------------+                               | comment        |
                                                | decision       |
      +------------------+                      | createdAt      |
      |    Student       |                      +----------------+
      |------------------|
      | id               |    +---------------------+
      | name             |    |  BidDeclaration     |
      | email            |    |---------------------|
      | matricola        |    | bidId(FK)           |
      | creditsRemaining |    | discussedWithSuprvs |
      | hasJob           |    | readyToStart        |
      | jobDescription   |    | noFunding           |
      | examTranscript   |    | hasJob / jobType    |
      | enrollmentYear   |    | jobInICT / company  |
      +------------------+    +---------------------+

      +------------------------+
      | TechnicalExamCommittee |
      |------------------------|
      | id                     |
      | thesisId(FK)           |
      | reviewerId(FK)         |
      | member2Id(FK)          |
      | member3Id(FK)          |
      | examDate               |
      | examLocation           |
      | techMark (18-30+lode)  |
      +------------------------+
```

### Key Relationships from CSV Evidence

From `ONGOING3` CSV and PDFs, each thesis record contains:

- **Candidate** name + email
- **Reviewer** (1 per thesis)
- **Start** / **End** dates
- **3M*** flag (3-month review overdue marker)
- **Title**, **Supervisor**, **Additional supervisor**
- **Challenging** (YES/NO) - determines max mark range
- **External** (YES/NO) + **External supervisor**
- **Primary topic**, **Secondary topic** (from ~30 topic taxonomy)
- **Abstract** (written by supervisor, displayed with word count)
- **Duration** computed in days and months

**[Evidence: ONGOING3 CSV row 1 headers, ONGOING3-4.pdf all pages]**

### Topic Taxonomy (30 topics)

From ONGOING3-3.pdf: Advanced data management, Blockchain, Computer Graphics and AR, Computer Science Education, Computer Security, Cutting edge technologies for SW development, Data visualization, Data warehousing, Distributed computing, Formal methods, Geometric modeling, High performance computing, HCI, Image processing and CV, IoT, Large-scale computing, Machine learning, Methods/techniques for HQ system development, Mobile development, Multi-agent systems, NLP, Network analysis, Principles/paradigms of programming languages, Software engineering, Software quality assurance, Software systems design and modelling, Speech processing, and more.

---

## 4. WORKFLOW STATE MACHINES

### 4.1 BiddingRound Lifecycle

**[Evidence: thesisworkflow.txt:57-64, ThesisProcess PDF slide 3]**

```
   +----------+  R3 creates   +-----------+  R3 starts    +--------+
   |          |-------------->| Scheduled |-------------->|  Open  |
   |  (new)   |               +-----------+               +---+----+
   +----------+                                               |
                                                              | R3 closes
                                                              v
                              +------------------+      +---------+
                              | ResultsPublished |<-----|  Closed |
                              +------------------+      +---------+
                                    R3 publishes results
```

**Annual Calendar** (5 rounds/year):

| Round | Proposals Collection | Bidding Window |
|---|---|---|
| February | Jan 20-30 | Feb 3-13 |
| April | Apr 1-10 | Apr 14-24 |
| July | Jul 1-10 | Jul 14-24 |
| September | Sep 4-14 | Sep 20-30 |
| December | Nov 20-30 | Dec 4-14 |

**[Evidence: ThesisProcess PDF slide 3, Bidding schedule screenshot]**

### 4.2 Bidding Process (Student Flow)

**[Evidence: ThesisProcess PDF slide 4]**

```
                    +---------------------------+
                    | Check: credits to pass    |
                    |   <= 15?                  |
                    +-------------+-------------+
                         YES      |    NO (>15) --> STOP, cannot bid
                                  v
                    +---------------------------+
                    | Student examines          |
                    | published proposals       |
                    +-------------+-------------+
                                  v
                    +---------------------------+
                    | Student CONTACTS          |   "contact = meeting
                    | supervisors (meeting,     |    (in person or online)
                    | NOT just email)           |    not sending an email"
                    +-------------+-------------+
                                  v
                    +---------------------------+
                    | Student submits bid       |--> Email containing:
                    | (ranked 1-2-3)            |   - 3 proposals (ranked)
                    +---------------------------+   - NOT all same supervisor
                                                    - Exam transcript
                                                    - Declarations (see below)
```

**Bid Declarations** (student must declare):

1. Has discussed all 3 proposals with their supervisors, who agreed on suitability
2. Ready to start work immediately
3. Will not receive funding for thesis work
4. Has/has not a full/part-time job (if yes + ICT field: describe company)

**Suitability criteria**: track/study plan, passed exams providing foundations, challenging theses need good marks.

### 4.3 Bids Evaluation (Admin Flow)

**[Evidence: ThesisProcess PDF slide 5]**

```
   +-----------------------------+
   | Work group examines bids    |
   | Criteria:                   |
   | - suitability               |
   | - workload balancing        |
   | - conflict resolution       |
   |   (career + suitability)    |
   +--------+--------------------+
            |
    +-------+--------+
    v                v
+------------+  +-------------------------------+
| NOT assigned|  | ASSIGNED (may be 1st/2nd/3rd)|
| -> suggest  |  | -> communicate proposal +    |
|   another   |  |   reviewer                   |
|   proposal  |  +-------------------------------+
+-----+------+
      v
+-------------+
| Re-bid for  |   "No looping till reaching an assignment"
| a still-    |   One extra round within same session,
| available   |   then result is assignment or refusal
| proposal    |
+-------------+
```

**KEY RULE**: If a student **refuses** an assigned thesis, they must bid again in the **next round** (no loop).

**[Evidence: ThesisProcess PDF slide 5]**

### 4.4 Thesis Lifecycle

**[Evidence: thesisworkflow.txt:76-95, ThesisProcess PDF slides 7-9]**

```
+------------+ assignment +----------+  3 months  +-----------------+
|NotAssigned |----------->| Assigned |----------->| InReview        |
+------------+            +----------+  mandatory  |(3-month check) |
                               |       review mtg  +-------+-------+
                               |                           |
                          student/sup                  +---+---+
                          cancels                      v       v
                               |               +----------+ +------------------+
                               v               | Accepted | |RevisionsRequested|
                          +----------+         +----+-----+ +--------+---------+
                          |Must re-  |              |                |
                          |bid next  |              v                v
                          |round     |    +--------------+   (cycle back to
                          +----------+    |  Submitted   |    InReview)
                                          |(final thesis)|
                                          +------+-------+
                                                 | sup approves
                                                 v
                                          +--------------+
                                          |ReadyForExam  |
                                          +--------------+
```

**Termination conditions**:

- Supervisor decides work is terminated -> student may take final exam
- Student loses interest -> must bid again next round
- Supervisor decides no chance to terminate successfully -> student must bid again

**[Evidence: ThesisProcess PDF slide 9]**

### 4.5 Final Exam Enrollment (New Regime: enrolled from 2023/24)

**[Evidence: Final Exam 2023/24 PDF slides 2-8]**

```
T-40 days                    T-30 days                   T-15 days       T-2 days     T=0
   |                             |                           |              |           |
   v                             v                           |              |           |
Student submits          Student hands draft                 |              |           |
request via UniGe        to reviewer                         |              |           |
online system                |                               |              |           |
   |                         v                               |              |           |
   v                    Reviewer reads &                     |              |           |
Supervisor              discusses with student               |              |           |
approves request             |                               |              |           |
   |                         |                               |              |           |
   +-------------------------+                               |              |           |
   v                                                         |              |           |
Student uploads final version ------------------------------>|              |           |
   |                                                         |              |           |
   v                                                         |              |           |
Supervisor approves uploaded doc --------------------------->+              |           |
   |                                                                        |           |
   v                                                                        |           |
[All complete by T-15] ------------------------------------------------->  +           |
                                                                            |           |
                                                                Student uploads         |
                                                                slides (PDF+PPT)        |
                                                                            |           |
                                                                            v           v
                                                                  Technical Exam -> Final Exam
```

### 4.6 Grading Formula (New Regime)

**[Evidence: Final Exam 2023/24 PDF slide 8]**

```
Technical Exam mark: 18-30 (e lode for challenging) or 18-27 (non-challenging)
   Committee: reviewer + 2 faculty members (NOT supervisor or their group)

WAV = weighted average of all courses + "Final Dissertation" (weight=30 credits)
   where "30 e lode" counts as 31
   "Final Dissertation" score = technical exam result

FM = final exam committee mark (0-4)

RES = round(WAV + FM)

IF thesis is challenging AND RES >= 110:
   Committee decides between 110 and 110 cum laude
ELSE:
   Final mark = min(RES, 110)
```

### 4.7 Grading Formula (Old Regime, enrolled till 2022/23)

**[Evidence: Final Exam 2022/23 PDF slide 5]**

```
WAV = weighted average of course marks ("30 e lode" = 33)
TM  = thesis marks: up to 10 (challenging) or up to 6 (non-challenging)
FM  = WAV + TM

IF challenging AND FM > 113:
   Committee may decide 110 or 110 e lode
ELSE:
   Final mark = min(FM, 110)
```

---

## 5. UI MAP (Reconstructed from Screenshots)

**[Evidence: Bidding schedule screenshot, Available Proposals screenshot, March 2026 Technical exams screenshot, Graduation days screenshot, Short guidelines screenshot, thesisworkflow.txt:175-277]**

### Current AulaWeb Navigation (from screenshot sidebar)

```
FINAL DISSERTATION - 90537 (AulaWeb 2025/26)
|-- General
|   |-- "This special AulaWeb course is..."
|   |-- News
|   |-- Forum for communicating with...
|   +-- FAQ
|-- March 2026 Final exam
|   +-- March 2026 Technical exams committee, when and where
|-- How to graduate
|   |-- Graduation days and committees
|   |-- Bidding schedule
|   |-- ThesisProcess- Thesis assignment...
|   |-- Thesis Process: Final exam (2023/24+)
|   |-- Thesis Process: Final exam (till 2022/23)
|   +-- AVAILABLE PROPOSALS: FEBRUARY 2026
|-- Writing the thesis
|   |-- Short guidelines on how to face...
|   |-- Latex Thesis Template
|   +-- Word Thesis Template
|-- ONGOING: The ongoing theses...
|-- Archive
+-- New section
```

### Proposed System Screens (from thesisworkflow.txt)

| # | Screen | Role | Purpose |
|---|--------|------|---------|
| S1 | Student: Bidding Tab | R1 | View round status, browse proposals (title+abstract), manage ranked bids, "No bidding" |
| S2 | Student: Results Tab | R1 | See Assigned/Not Assigned, proposal details, supervisor, reviewer |
| S3 | Student: My Thesis | R1 | Thesis status, timeline, review feedback, attachments |
| S4 | Reviewer: Theses List | R2 | List of assigned-to-review theses with status filters |
| S5 | Reviewer: Thesis Detail | R2 | Proposal abstract, docs, review form (Approve/RequestChanges/Reject) |
| S6 | Admin: Proposals CRUD | R3 | Create/edit/publish/close/archive proposals with abstract (<=200 words, live counter) |
| S7 | Admin: Bidding Rounds | R3 | Create/start/close/publish rounds |
| S8 | Admin: Assignment Console | R3 | Assign/unassign/reassign students to proposals |
| S9 | Admin: Reviewer Assignment | R3 | Assign reviewers to theses |
| S10 | Admin: Audit Log | R3 | All actions logged: who, what, when, old/new values |

---

## 6. KEY BUSINESS RULES & VALIDATORS

**[Evidence: thesisworkflow.txt:220-236]**

| ID | Rule | Source |
|---|---|---|
| FR-ABS-01 | Proposal abstract must not exceed 200 words | thesisworkflow.txt:225 |
| FR-ABS-02 | Word count by whitespace splitting | thesisworkflow.txt:226 |
| FR-ABS-03 | UI shows live counter "Words: X/200" | thesisworkflow.txt:227 |
| FR-ABS-04 | Publish blocked if abstract > 200 words | thesisworkflow.txt:228 |
| FR-BID-01 | Student selects exactly 3 proposals, ranked 1-2-3 | ThesisProcess slide 4 |
| FR-BID-02 | Not all 3 from same supervisor | ThesisProcess slide 4 |
| FR-BID-03 | Student can bid only when round = Open | thesisworkflow.txt:127 |
| FR-BID-04 | Student credits to pass must be <= 15 | ThesisProcess slide 4 |
| FR-BID-05 | Passed exam condition verified at end of exam session (Feb/Jul/Sep) or bidding month (Apr/Dec) | ThesisProcess slide 3 |
| FR-RULE-01 | Student cannot have >1 active assignment | thesisworkflow.txt:232 |
| FR-RULE-02 | Proposal capacity not exceeded without override | thesisworkflow.txt:233 |
| FR-RULE-03 | Student refusing assigned thesis must bid again next round | ThesisProcess slide 5 |
| FR-RULE-04 | All manual overrides logged | thesisworkflow.txt:235 |
| FR-RULE-05 | 3-month mandatory reviewer meeting (3M* flag in spreadsheet) | ThesisProcess slide 7, ONGOING3 CSV |
| FR-RULE-06 | Challenging thesis flag affects max grade range | Final Exam slides |
| FR-RULE-07 | Technical committee excludes supervisor and their research group | Final Exam 2023/24 slide 4 |
| FR-RULE-08 | Thesis document must include AI usage declaration | ThesisProcess slide 8 |

---

## 7. GAP ANALYSIS: Questions for Professor

### 7.1 MUST (Blocking for MVP)

| # | Question | Why It Matters |
|---|----------|----------------|
| M1 | **Authentication**: Should we integrate with UniGe SSO/LDAP, or is standalone auth acceptable for MVP? | Determines entire auth architecture |
| M2 | **Bid submission**: The current process is "sends email containing." Should the system replace email entirely, or work alongside it? | Core workflow design |
| M3 | **Assignment algorithm**: Is there a formal algorithm for evaluating bids (suitability + workload balancing + conflict resolution), or is it purely manual human judgment? | Determines if assignment is automated or just a manual console |
| M4 | **"Credits to pass <= 15" check**: Should the system verify this automatically (integration with UniGe student records), or is it self-declared by the student? | External integration dependency |
| M5 | **Exam transcript upload**: Students currently upload a document listing passed/pending exams. Should this be a file upload field or structured data? | Data model for bid |
| M6 | **Reviewer assignment logic**: Is there a rule/algorithm for selecting reviewers, or is it fully manual by the work group? | Feature scope |
| M7 | **Which grading regime to support?** Both old (enrolled till 2022/23) and new (from 2023/24), or only the new one? Old-regime students are nearly graduated by now. | Grading module complexity |
| M8 | **Data migration**: Should the system import existing data from ONGOING3 spreadsheet, or start fresh? | Seeding/migration effort |

### 7.2 SHOULD (Important but won't block first release)

| # | Question | Context |
|---|----------|---------|
| S1 | **Thesis abroad flow**: Should the system support the special "dissertation abroad" path (Erasmus), or handle it out-of-band? | ThesisProcess slide 6 shows a separate flow |
| S2 | **Notification channels**: Email only, or also in-app notifications? Push? | thesisworkflow.txt:239-256 lists events |
| S3 | **Technical exam committee formation**: Should the system assist in forming committees (suggest members by topic familiarity), or just record them? | March 2026 screenshot shows manual assignment |
| S4 | **Faculty workload dashboard**: ONGOING3-2/3 PDFs show effort scoring formulas. Should the system compute these? | Significant feature to replicate |
| S5 | **Word count on abstract**: The CSV shows actual word counts (e.g., 821, 730, 516...) that clearly exceed 200. Are these legacy entries, or does the 200-word limit apply only going forward? | Several existing abstracts far exceed 200 words |
| S6 | **Bid declarations as checkboxes**: Should the 4 declarations be formal checkboxes the student must tick, or free-text? | ThesisProcess slide 4 |

### 7.3 NICE (Enhancements)

| # | Question | Context |
|---|----------|---------|
| N1 | Should the system support **proposal templates** for external/Erasmus theses? | Slide 6 |
| N2 | Should there be a **forum/FAQ** module built in, or keep using AulaWeb for that? | Screenshot shows forums in AulaWeb |
| N3 | **Thesis document templates** (LaTeX/Word) distribution via the system? | "Writing the thesis" section in AulaWeb |
| N4 | **Presentation slides upload** (2 days before exam): in-system or keep via AulaWeb? | Final Exam slides |
| N5 | **Historical analytics**: supervisor load over years, topic popularity trends? | ONGOING3-5 has years of data |

---

## 8. MINIMUM BUILD (MVP) SCOPE

### 8.1 In Scope for MVP

| Module | Features | Screens | Priority |
|---|---|---|---|
| **Auth & Users** | Login (email/password or SSO stub), role assignment (Student/Reviewer/Admin) | Login, Profile | P0 |
| **Proposal Management** | CRUD proposals, abstract with 200-word validator + live counter, publish/close/archive, topic tags, challenging flag, external flag | S6 | P0 |
| **Bidding Rounds** | Create round with dates, open/close/publish results, 5-round calendar | S7 | P0 |
| **Bid Submission** | Student selects 3 proposals ranked, attaches exam transcript (file upload), ticks 4 declarations, enforces "not all same supervisor" rule | S1 | P0 |
| **Assignment Console** | Admin views all bids per round, manually assigns student to proposal, creates Thesis record, communicates reviewer | S8 | P0 |
| **Thesis Status View** | Student sees assignment, supervisor, reviewer, status | S2, S3 | P0 |
| **Reviewer Dashboard** | Reviewer sees assigned theses, can leave feedback | S4, S5 | P1 |
| **Audit Log** | All admin/reviewer actions logged with timestamps | S10 | P1 |
| **Notifications** | Email notifications for key events (round opened, results published, assigned) | Background | P1 |

### 8.2 Deferred to V2

| Module | Reason |
|---|---|
| Automated assignment algorithm | Requires deep understanding of evaluation criteria; keep manual for MVP |
| Faculty workload calculator | Complex scoring formula from ONGOING3 PDFs |
| Technical exam committee management | Separate workflow; can remain manual initially |
| Final exam enrollment workflow | Integrates with UniGe online system |
| Grading calculation | Depends on official UniGe data (WAV) |
| Thesis abroad special flow | Edge case; can be handled manually |
| Historical data import from ONGOING3 spreadsheet | Migration task, not core feature |
| AI declaration tracking | Can be part of thesis document, not system-tracked |

### 8.3 MVP Technical Recommendations

**Data model**: 7 core tables - `User`, `Proposal`, `BiddingRound`, `Bid`, `BidDeclaration`, `Thesis`, `Review`, plus `AuditLog`

**Key constraints to implement from day 1**:

- Abstract <= 200 words (whitespace split) with live UI counter
- Max 3 bids per student per round, ranked
- Not all bids to same supervisor
- One active assignment per student
- Round status gate (bids only when Open)
- All admin actions audit-logged

**Estimated MVP screen count**: 10 screens (as listed in thesisworkflow.txt:266-277), which maps cleanly to a standard SPA with role-based routing.

---

## 9. GRADUATION SESSIONS & COMMITTEE DATA

**[Evidence: Graduation days and committees screenshot]**

### 9.1 Exam Sessions (Academic Year 2025/26)

| Session | Student Presentations | Proclamation | Committee (President + Members) |
|---|---|---|---|
| July 2025 | Jul 23, 24, 25 | Jul 25 | Alessandro Verri (P), Matteo Dell'Amico, Giorgio Delzanno, Gianna Reggio, Filippo Ricca |
| October 2025 | Oct 22, 23, 24 | Oct 24 | Alessandro Verri (P), Annalisa Barla, Maura Cerioli, Manuela Chessa, Enrico Puppo |
| December 2025 | Dec 17, 18 | Dec 18 dicembre | Alessandro Verri (P), Annalisa Barla, Maurizio Leotta, Viviana Mascardi, Nicoletta Noceti |
| March 2026 | Mar 25, 26, 27 | Mar 27 | Alessandro Verri (P), Davide Ancona, Daniele D'Agostino, Giovanni Lagorio, Gianna Reggio |

### 9.2 Technical Exam Committees (March 2026 Example)

**[Evidence: March 2026 Technical exams committee screenshot]**

Each candidate gets a **distinct** 3-person technical committee:

| Candidate | Committee Members | When | Where |
|---|---|---|---|
| ALI MELICA OMER | Manuela Chessa, Nicoletta Noceti, Matteo Moro | March 12, 17:00 | TBD |
| BAZZI CELESTE | Enrico Puppo, Manuela Chessa, Paola Magillo | TBD | TBD |
| CALZA ELISA | Stefano Rovetta, Viviana Mascardi, Daniele D'Agostino | TBD | TBD |
| CICALA RICCARDO | TBD | TBD | TBD |
| COSULICH MARCO | TBD | TBD | TBD |
| FUCIARELLI LAURA | TBD | TBD | TBD |
| LUPI FEDERICO | TBD | TBD | TBD |
| MARTINO ELENA | TBD | TBD | TBD |
| PARODI CHRISTIAN | TBD | TBD | TBD |
| SIDDI YRYSKELDI | TBD | TBD | TBD |
| TIMOSSI LUIGI | TBD | TBD | TBD |
| VALENTINI DARIO | TBD | TBD | TBD |

---

## 10. DATA VOLUME ESTIMATES

**[Evidence: ONGOING3-2.pdf, ONGOING3-3.pdf, ONGOING3-5.pdf]**

| Metric | Value | Source |
|---|---|---|
| Currently ongoing theses | ~64 | ONGOING3-2.pdf (totale: 58 primary + 15 additional = 61 supervisor roles) |
| Historical terminated theses | ~170 | ONGOING3-3.pdf (totale: 170 primary sup) |
| Total theses via bidding | ~156 (terminated) + 64 (ongoing) = ~220 | ONGOING3-2/3 PDFs |
| External theses ratio | ~30% | ONGOING3-2.pdf: 19 external out of 64 = 29.69% |
| Challenging thesis ratio | ~69-82% | ONGOING3-2.pdf: 44/64 = 68.75%; ONGOING3-3.pdf: 128/156 = 82.05% |
| Faculty members (active supervisors) | ~30+ | ONGOING3-2.pdf list |
| Available proposals per round | ~15-30 | ONGOING3-4.pdf (Feb 2026 round) |
| Topic categories | ~30 | ONGOING3-3.pdf right table |
| Top topics by count | Machine learning (9), Software engineering (10), Image processing/CV (5), Computer Security (5) | ONGOING3-3.pdf |

---

## 11. THESIS DOCUMENT REQUIREMENTS

**[Evidence: ThesisProcess PDF slide 8, Short guidelines screenshot]**

### Required Sections

1. **Abstract** (up to 200 words)
2. **Introduction**
3. **Related work / state of the art** chapter
4. **Background** chapter (presenting technical concepts used)
5. **Conclusions**
6. **AI Declaration**: detailing which content was generated by AI (text, figures, images, code), stating the AI system used, and the level of AI usage
   - Exception: not required for AI used only for editing/grammar checking, or when the thesis itself is about using AI to generate content

### Templates Available

- LaTeX Thesis Template (via AulaWeb)
- Word Thesis Template (via AulaWeb)

---

*Document generated: 2026-03-01*
*Source: Analysis of 16 files in FINAL DISSERTATION - 90537 project directory*
