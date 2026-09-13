# ANTI-MATRIX AI DATABASE SAFETY RULES

> **PERMANENT AI PROJECT SAFETY INSTRUCTION FILE**  
> **Target Project:** ANTI-MATRIX Website  
> **Status:** MANDATORY & NON-NEGOTIABLE  
> **Applicability:** Every AI coding agent, prompt, developer, and automated workflow interacting with this codebase.

---

## PURPOSE

The purpose of this file is to ensure that every future AI coding task understands:

**DO NOT MODIFY EXISTING PRODUCTION DATABASE CONTENT.**

Before making **ANY** code, database, migration, feature, UI, backend, testing, or deployment change, the AI agent must read this file first.

---

## MANDATORY DATABASE SAFETY RULES

These rules are **NON-NEGOTIABLE**:

1. **NEVER delete existing production data.**
2. **NEVER modify existing production records** unless the user's current request explicitly requires changing that specific record.
3. **NEVER reset the production database.**
4. **NEVER recreate the production database.**
5. **NEVER truncate production tables.**
6. **NEVER drop production tables.**
7. **NEVER run destructive migrations against production.**
8. **NEVER run database seed/reset scripts against production.**
9. **NEVER use:**
   ```sql
   DROP TABLE;
   DROP DATABASE;
   TRUNCATE;
   DELETE FROM <table>;
   ```
   for testing or development purposes.
10. **NEVER use:**
    ```python
    db.drop_all()
    ```
    or equivalent destructive ORM / database reset operations.

---

## EXISTING DATA MUST BE PRESERVED

The following existing production data must remain intact:

- **Users**
- **Job Postings**
- **Job Codes**
- **Applications**
- **Application IDs**
- **Employees**
- **Employee IDs**
- **Employee credentials**
- **Payments**
- **Payment records**
- **Money Management transactions**
- **Uploaded resumes**
- **Uploaded documents**
- **Document templates**
- **Email templates**
- **Email logs**
- **Colleges**
- **Departments**
- **Internship plans**
- **Contact inquiries**
- **Any other existing database tables or records**

*Do not assume that only the above tables exist. Always inspect the actual schema before making database changes.*

---

## NO TESTING AGAINST REAL DATA

AI agents **MUST NOT** modify existing production records just to test a feature.

**Do NOT:**
- Change an existing candidate's status for testing
- Change an existing payment status for testing
- Change an existing Employee ID for testing
- Change an existing Application ID for testing
- Change an existing employee password for testing
- Modify an existing job posting for testing
- Modify an existing transaction for testing
- Delete an existing candidate/record from production under the assumption that it is a test record
- Upload a test document over an existing document

---

## HOW TO TEST

If testing requires database records:

1. **CREATE A TEMPORARY TEST RECORD.**
2. Use clearly identifiable test data.
   - **Name:** `AI TEST CANDIDATE`
   - **Email:** `ai-test@example.invalid`
   - **Phone:** `9999999999`
   - **Job:** `TEST ONLY`
   - **Application ID:** Use a safely generated test identifier that cannot collide with production data (e.g. `TEST-APP-XXXXX`).
3. After testing is completely finished:
   - **DELETE ONLY THE TEMPORARY TEST RECORDS CREATED BY THE AI AGENT.**

> **IMPORTANT:**  
> The AI agent may delete **ONLY** the test data that it created itself during the current test.  
> It must **NEVER** delete or modify existing production records.

---

## TEST FILES

If a temporary file is required for testing:

1. Create the temporary file.
2. Use it for testing.
3. Verify the test is complete.
4. Delete the temporary test file.

- Never overwrite an existing production file.
- Never delete an existing uploaded candidate file.
- Never replace an existing template merely for testing.

---

## DATABASE MIGRATIONS

If a schema change is genuinely required:

**Use an additive, backward-compatible migration.**

Examples of safe additive changes:
- Add a new nullable column (`ALTER TABLE ... ADD COLUMN ... DEFAULT NULL`).
- Add a new table (`CREATE TABLE IF NOT EXISTS ...`).
- Add a safe index.
- Add a foreign-key relationship without destroying or modifying existing rows.

**Before applying a migration:**
1. Inspect the current schema.
2. Identify affected tables.
3. Confirm existing records will remain intact.
4. Make the smallest possible schema change.
5. Do not reset or recreate the database.

---

## NO BULK UPDATES

Do **NOT** perform bulk updates merely to make existing data match the new feature.

For example, **NEVER** do:
```sql
UPDATE applications SET status = 'APPLIED';
UPDATE applications SET payment_status = 'PENDING';
UPDATE employees SET ...;
```
unless the user explicitly requested that exact bulk modification.

**Always preserve existing values.**

---

## PRODUCTION DATABASE IS THE SOURCE OF TRUTH

If code contains:
- Sample data
- Mock data
- Demo records
- Hard-coded candidates
- Fake jobs
- Seed data

**DO NOT** replace real production database data with those values.
- Read the actual database records.
- Do not insert sample/demo records into production.

---

## BEFORE ANY DATABASE CHANGE

The AI agent must first determine:

1. **Does this task actually require a database change?**
   - If **NO**: Do not touch the database.
   - If **YES**: Determine the smallest safe, additive change.

2. **Then verify:**
   - Existing rows remain intact.
   - Existing IDs remain intact.
   - Existing relationships remain intact.
   - Existing files remain intact.
   - Existing payments remain intact.

---

## ID PRESERVATION

**NEVER change existing:**

- **Application IDs** (e.g., `AM-APP-000001`)
- **Employee IDs** (e.g., `AM2182`)
- **Job Codes** (e.g., `JB1401`)

Existing identifiers must remain unchanged. New records may receive new unique identifiers.

---

## PAYMENT DATA

Payment records are especially sensitive.

**Never:**
- Delete payments
- Alter historical payment amounts
- Alter historical payment dates
- Alter historical payment references
- Fake payment success on existing records
- Mark existing payments as verified for testing

*If payment functionality must be tested: Use a safe test/sandbox environment or create a clearly isolated test record.*

---

## EMPLOYEE DATA

- Never modify existing employees just to test employee creation.
- Never change an existing Employee ID.
- Never overwrite an existing employee's password.
- Never create a duplicate employee for an existing Application ID.
- If testing employee creation: Use a temporary test application.

---

## MONEY MANAGEMENT

Money Management records must never be changed during feature testing.

**Never:**
- Add fake transactions to production
- Delete transactions
- Clear transactions
- Modify existing transaction amounts
- Modify existing transaction dates
- Modify existing payment references

*If a test transaction is absolutely required: Create a clearly marked temporary test transaction and delete ONLY that transaction after testing.*

---

## DOCUMENTS AND TEMPLATES

Never overwrite an existing production:
- Offer Letter template
- Email template
- Resume
- Employee document
- Generated document

**When testing document generation:**
1. Create a temporary test document.
2. Delete the temporary test document after testing.
3. The original master template must remain unchanged.

---

## BACKUP / VERIFICATION

Before any potentially risky database operation:
- Inspect the current database state.

After the operation:
- Verify that:
  - Existing record counts have not unexpectedly decreased.
  - Existing IDs remain present.
  - Existing relationships remain intact.
  - No unrelated records were changed.

> **If unexpected data modification occurs:**  
> **STOP IMMEDIATELY.** Do not continue making additional changes.

---

## PRODUCTION VS TESTING

Always distinguish:

$$\text{\textbf{PRODUCTION DATA}} \quad \neq \quad \text{\textbf{TEMPORARY TEST DATA}}$$

- Never assume an existing record is a test record simply because its name looks like a test record.
- Only delete test data that the AI agent explicitly created during the current test.

---

## WHEN USER REQUESTS A FEATURE

The AI agent must follow this strict sequence:

1. **Read this file (`AI_DATABASE_SAFETY.md`).**
2. **Inspect the existing implementation.**
3. **Determine whether the feature can be implemented without database changes.**
4. **If database changes are required, use the safest additive approach.**
5. **Preserve all existing records.**
6. **Test using temporary data where necessary.**
7. **Delete only temporary test data created by the AI agent.**
8. **Verify production data remains intact.**

---

## ABSOLUTELY FORBIDDEN

Never execute these against production:
- `DROP DATABASE`
- `DROP TABLE`
- `TRUNCATE TABLE`
- `db.drop_all()`
- Database reset
- Database recreation
- Production reseeding
- Bulk deletion
- Bulk status reset
- Bulk payment reset
- Bulk employee reset
- Bulk Application ID reset
- Bulk Employee ID reset

---

## FINAL RULE

> **WHEN IN DOUBT: DO NOT MODIFY EXISTING DATA.**  
> Stop and inspect the implementation first.

A feature should be implemented by changing:
- Application code
- UI
- Backend logic
- Configuration
- Additive schema

rather than changing or destroying existing production records.

---

## AI ACKNOWLEDGEMENT

Before performing any database-affecting operation, the AI agent must internally verify:

> *"I have read `AI_DATABASE_SAFETY.md` and will preserve all existing production data. Any testing data I create will be temporary and will be removed after testing is complete."*

*This acknowledgement does NOT authorize destructive operations. The rules above always take absolute priority.*
