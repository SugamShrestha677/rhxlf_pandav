# LMS API Contract

## Base Information

- Base URL: `http://localhost:8000/api/`
- Auth: JWT via `Authorization: Bearer <access_token>`
- Token refresh: `POST /api/accounts/auth/token/refresh`
- Server port: Django default `8000`
- Middleware: `CorsMiddleware`, `SessionMiddleware`, `CommonMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware`, `MessageMiddleware`, `XFrameOptionsMiddleware`

## Response Conventions

- Success endpoints usually return the resource payload directly for DRF CRUD endpoints.
- Custom auth and action endpoints return a shared envelope: `{"success": true, "message": "...", "data": {...}}`.
- Validation and permission errors should be treated as JSON responses with HTTP status codes and field-level details.
- After the backend normalization work in this repo, error responses are standardized to:

```json
{
  "success": false,
  "message": "Request failed",
  "errors": {},
  "status_code": 400
}
```

## Authentication

- Mechanism: JWT (`rest_framework_simplejwt.authentication.JWTAuthentication`)
- Header format: `Authorization: Bearer <access_token>`
- Access token lifetime: 15 minutes
- Refresh token lifetime: 7 days
- Refresh rotation: enabled
- Blacklist after rotation: enabled

For a secure Next.js integration, the preferred storage is an HTTP-only cookie set by the frontend or a BFF layer. If tokens are kept in the browser, keep them out of `localStorage` if possible.

## Accounts Module

### POST /api/accounts/users/create

- Purpose: Create a user with organization email, personal email, and role.
- Auth: required, admin/staff only.
- Body:

```json
{
  "email": "user@org.com",
  "personal_email": "user@gmail.com",
  "role": "student"
}
```

- Success: `201 Created`

```json
{
  "success": true,
  "message": "User created successfully",
  "data": {
    "user": {
      "id": 1,
      "email": "user@org.com",
      "personal_email": "user@gmail.com",
      "role": "student",
      "must_change_password": true
    },
    "email_sent": true,
    "email_sent_to": "user@gmail.com"
  }
}
```

### POST /api/accounts/auth/login

- Purpose: Login using organization email and password.
- Auth: none.
- Body:

```json
{
  "email": "user@org.com",
  "password": "secret"
}
```

- Success: `200 OK`

```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "user": {
      "id": 1,
      "email": "user@org.com",
      "personal_email": "user@gmail.com",
      "role": "student",
      "must_change_password": false,
      "profile_completed": false
    },
    "tokens": {
      "refresh": "...",
      "access": "..."
    },
    "redirect_to": "/dashboard/"
  }
}
```

- Errors: `400` for validation, `401` for invalid credentials, `403` for deactivated account.

### POST /api/accounts/auth/logout

- Purpose: Blacklist a refresh token.
- Auth: required.
- Body:

```json
{ "refresh": "<refresh_token>" }
```

- Success: `200 OK`

```json
{ "success": true, "message": "Logout successful", "data": null }
```

### POST /api/accounts/auth/token/refresh

- Purpose: Exchange a refresh token for a new access token.
- Auth: none.
- Body:

```json
{ "refresh": "<refresh_token>" }
```

- Success: `200 OK`

```json
{ "access": "...", "refresh": "..." }
```

### POST /api/accounts/auth/first-login

- Purpose: Replace the temporary password with a permanent password.
- Auth: required.
- Body:

```json
{
  "new_password": "NewStrongPassword!123",
  "confirm_password": "NewStrongPassword!123"
}
```

- Success: `200 OK`

```json
{
  "success": true,
  "message": "Password set successfully! Welcome to Leapfrog Connect.",
  "data": {
    "tokens": { "refresh": "...", "access": "..." },
    "user_status": {
      "must_change_password": false,
      "profile_completed": false
    },
    "next_step": "Complete your profile at /api/accounts/users/me/"
  }
}
```

### POST /api/accounts/auth/change-password

- Purpose: Change an authenticated user password.
- Auth: required.
- Body:

```json
{
  "old_password": "CurrentPassword!",
  "new_password": "NewStrongPassword!123",
  "confirm_password": "NewStrongPassword!123"
}
```

- Success: `200 OK`

```json
{ "success": true, "message": "Password changed successfully", "data": null }
```

### POST /api/accounts/auth/forgot-password

- Purpose: Start password reset flow.
- Auth: none.
- Body:

```json
{ "email": "user@org.com" }
```

- Success: `200 OK`

```json
{
  "success": true,
  "message": "If the account exists, a password reset link has been sent to your personal email.",
  "data": null
}
```

### POST /api/accounts/auth/reset-password

- Purpose: Reset password with a reset token.
- Auth: none.
- Body:

```json
{
  "token": "reset-token",
  "new_password": "NewStrongPassword!123",
  "confirm_password": "NewStrongPassword!123"
}
```

- Success: `200 OK`

```json
{ "success": true, "message": "Password reset successful. You can now login with your new password.", "data": null }
```

### Users CRUD

- `GET /api/accounts/users/` list users
- `POST /api/accounts/users/` create a generic user via DRF model serializer
- `GET /api/accounts/users/{id}/` retrieve user
- `PUT /api/accounts/users/{id}/` update user
- `PATCH /api/accounts/users/{id}/` partial update user
- `DELETE /api/accounts/users/{id}/` delete user

Response shape: DRF serializer JSON object or array.

### User actions

- `GET /api/accounts/users/me/` get current user profile
- `PATCH /api/accounts/users/me/` update current user profile
- `POST /api/accounts/users/{id}/deactivate/`
- `POST /api/accounts/users/{id}/activate/`
- `POST /api/accounts/users/{id}/change_role/`

### Staff permissions

- `GET /api/accounts/staff-permissions/`
- `POST /api/accounts/staff-permissions/`
- `GET /api/accounts/staff-permissions/{id}/`
- `PUT /api/accounts/staff-permissions/{id}/`
- `PATCH /api/accounts/staff-permissions/{id}/`
- `DELETE /api/accounts/staff-permissions/{id}/`

## Courses Module

### Courses

- `GET /api/courses/`
- `POST /api/courses/`
- `GET /api/courses/{id}/`
- `PUT /api/courses/{id}/`
- `PATCH /api/courses/{id}/`
- `DELETE /api/courses/{id}/`
- `POST /api/courses/{id}/publish/`
- `POST /api/courses/{id}/archive/`

Create/update body fields include title, description, short_description, level, duration_weeks, total_hours, thumbnail_url, preview_video_url, price, is_free, dates, max_students, instructor, prerequisites, target_audience, and learning_outcomes.

### Nested course resources

- `GET /api/courses/{course_id}/modules/`
- `POST /api/courses/{course_id}/modules/`
- `GET /api/courses/{course_id}/modules/{id}/`
- `PUT /api/courses/{course_id}/modules/{id}/`
- `PATCH /api/courses/{course_id}/modules/{id}/`
- `DELETE /api/courses/{course_id}/modules/{id}/`

- `GET /api/courses/{course_id}/modules/{module_id}/contents/`
- `POST /api/courses/{course_id}/modules/{module_id}/contents/`
- `GET /api/courses/{course_id}/modules/{module_id}/contents/{id}/`
- `PUT /api/courses/{course_id}/modules/{module_id}/contents/{id}/`
- `PATCH /api/courses/{course_id}/modules/{module_id}/contents/{id}/`
- `DELETE /api/courses/{course_id}/modules/{module_id}/contents/{id}/`

- `GET /api/courses/{course_id}/assessments/`
- `POST /api/courses/{course_id}/assessments/`
- `GET /api/courses/{course_id}/assessments/{id}/`
- `PUT /api/courses/{course_id}/assessments/{id}/`
- `PATCH /api/courses/{course_id}/assessments/{id}/`
- `DELETE /api/courses/{course_id}/assessments/{id}/`

- `GET /api/courses/{course_id}/reviews/`
- `POST /api/courses/{course_id}/reviews/`
- `GET /api/courses/{course_id}/reviews/{id}/`
- `PUT /api/courses/{course_id}/reviews/{id}/`
- `PATCH /api/courses/{course_id}/reviews/{id}/`
- `DELETE /api/courses/{course_id}/reviews/{id}/`

- `GET /api/courses/{course_id}/announcements/`
- `POST /api/courses/{course_id}/announcements/`
- `GET /api/courses/{course_id}/announcements/{id}/`
- `PUT /api/courses/{course_id}/announcements/{id}/`
- `PATCH /api/courses/{course_id}/announcements/{id}/`
- `DELETE /api/courses/{course_id}/announcements/{id}/`

### Enrollments

- `GET /api/enrollments/`
- `POST /api/enrollments/`
- `GET /api/enrollments/{id}/`
- `PUT /api/enrollments/{id}/`
- `PATCH /api/enrollments/{id}/`
- `DELETE /api/enrollments/{id}/`
- `POST /api/enrollments/{id}/complete_module/`
- `POST /api/enrollments/{id}/complete_content/`

Enrollment body expects at least `course`; `student` is assigned by backend in the create flow.

### Student assessments

- `GET /api/student-assessments/`
- `POST /api/student-assessments/`
- `GET /api/student-assessments/{id}/`
- `PUT /api/student-assessments/{id}/`
- `PATCH /api/student-assessments/{id}/`
- `DELETE /api/student-assessments/{id}/`

### Certificates

- `GET /api/certificates/`
- `GET /api/certificates/{id}/`
- `POST /api/certificates/generate_certificate/`

## Status Codes to Expect

- `200 OK`: successful reads and actions
- `201 Created`: successful creates
- `400 Bad Request`: validation or bad payload
- `401 Unauthorized`: missing or invalid JWT
- `403 Forbidden`: permission denied
- `404 Not Found`: missing resource

## Frontend Integration Notes

1. Send access tokens in the `Authorization` header on every protected request.
2. Use `credentials: 'include'` only if you later move token handling into cookies.
3. Keep request bodies JSON, and send `Content-Type: application/json`.
4. Read `message`, `data`, and `errors` for feedback on custom endpoints and normalized errors.
5. For login and password-reset emails, the backend now uses `FRONTEND_BASE_URL` so those links can be switched per environment.