```markdown
# SKILLS.md

## 1. Add or modify a field in the Item API response model

### File Paths to Modify
- `backend/app/models.py`

### Steps
1. Open `backend/app/models.py`.
2. Locate the `ItemPublic` class.
3. Add or modify the desired field within the `ItemPublic` class.
4. Save the changes.

### Regenerate Frontend TypeScript Client
- Run the following command in the `frontend` directory:
  ```shell
  npm run generate-client
  ```

### Safety Rules
- Ensure any new fields added are non-breaking changes for existing API consumers.

## 2. Add a new environment variable to the backend config

### File Paths to Modify
- `backend/app/core/config.py`
- `.env`

### Steps
1. Open `backend/app/core/config.py`.
2. Add a new field in the `Settings` class with a default value or type.
3. Open the `.env` file located one level above the `backend` directory.
4. Add the new environment variable with its value.
5. Save the changes in both files.

### Safety Rules
- Never commit sensitive information such as passwords or secret keys to version control.

## 3. Add a new API endpoint to the items router

### File Paths to Modify
- `backend/app/api/routes/items.py`

### Steps
1. Open `backend/app/api/routes/items.py`.
2. Define a new function for the API endpoint using FastAPI decorators (e.g., `@router.get`, `@router.post`).
3. Implement the logic for the new endpoint.
4. Ensure the function has proper response models and error handling.
5. Save the changes.

### Regenerate Frontend TypeScript Client
- Run the following command in the `frontend` directory:
  ```shell
  npm run generate-client
  ```

### Safety Rules
- Ensure new endpoints are properly authenticated and authorized.

## 4. Perform a database schema migration

### File Paths to Modify
- `backend/alembic/env.py` (if exists)
- `backend/alembic/versions/` (create new migration files here)

### Steps
1. Navigate to the `backend` directory.
2. Run the following command to create a new migration:
   ```shell
   alembic revision --autogenerate -m "describe changes"
   ```
3. Review the generated migration script in `backend/alembic/versions/`.
4. Apply the migration to the database:
   ```shell
   alembic upgrade head
   ```

### Safety Rules
- Never apply migrations directly to the production database without prior review.
- Always backup the database before applying migrations.
```