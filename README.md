# QA Navigator

AI QA Agent — Phase 1: Frontend Foundation

Build the frontend foundation of a SaaS-ready application called AI QA Agent.

Product concept

AI QA Agent is a functional QA platform that will eventually:

GitHub repository
→ Code analysis
→ Functional features
→ User Stories
→ Acceptance Criteria
→ Gherkin scenarios
→ Jira
→ Playwright tests
→ Test execution
→ QA coverage

IMPORTANT:

The AI/code-analysis engine will NOT be implemented in this phase.

The backend will eventually be a completely independent Python/FastAPI service.

The frontend must therefore communicate with the backend exclusively through a REST API abstraction.

1. Technology

Use:

React

TypeScript

Vite

Tailwind CSS

shadcn/ui where useful

Use a clean, professional B2B SaaS design.

The application is aimed primarily at:

QA Engineers

Functional Testers

Automation Engineers

Developers

Product Owners

The interface should feel like a professional QA/productivity tool, not a generic AI chatbot.

2. Application layout

Create a persistent sidebar.

Navigation:

Dashboard

Projects

Backlog

Gherkin

Automation

Coverage

Settings

Top bar:

Current project

User/workspace

Notifications

Settings

Profile

3. Dashboard

Create a professional dashboard.

Display:

Projects

Number of active projects.

User Stories

Example:

31

Gherkin scenarios

Example:

118

Automated tests

Example:

76

Automation coverage

Example:

87.9%

Use cards with subtle visual hierarchy.

Add a recent activity section.

Example:

"Analysis completed"

"12 User Stories approved"

"8 Playwright tests generated"

"3 tests failed"

4. Projects page

Display projects as cards or a table.

Each project should show:

Project name

Repository

Branch

Jira status

Last analysis

Number of User Stories

Number of automated tests

Actions:

Open

Analyze

Settings

Add:

"+ New Project"

5. Create Project

Create a form:

Project name

Repository source:

GitHub

Local repository

GitHub repository URL

GitHub branch

Jira integration:

Not connected

Connected

Jira project key

AI engine:

Ollama / Local

Other provider (disabled for now)

Do not actually connect to GitHub, Jira or Ollama yet.

Use mocked API responses.

6. Project detail

Create a project overview.

Example:

AI QA Agent

Repository:
github.com/example/project

Branch:
main

Last analysis:
31 August 2026

Status:
Ready

Display statistics:

Features
42

User Stories
31

Gherkin
118

Playwright
76

Coverage
87.9%

Primary CTA:

"Analyze Repository"

7. Analysis page

Create a visual analysis workflow.

Steps:

Repository

Architecture

Routes

Components

APIs

Features

User Stories

Gherkin

Show progress.

Example:

✓ Repository retrieved

✓ Architecture analyzed

✓ Routes analyzed

✓ Components analyzed

⟳ Detecting functional features

○ Generate User Stories

○ Generate Gherkin

Use statuses:

pending

running

completed

failed

The UI must be designed so these states will later come from the Python API.

8. Backlog page

This is one of the most important screens.

Display generated User Stories in a table.

Columns:

Feature

User Story

Confidence

Acceptance Criteria

Gherkin

Jira

Automation

Status

Example:

| Feature | Story | Confidence | AC | Gherkin | Jira | Tests | Status |

Use badges for:

Draft

Needs Review

Approved

Created

Out of Sync

9. User Story detail

Clicking a User Story opens a detailed view.

Display:

User Story

Title

Description

Epic

Feature

Confidence

Source files

Acceptance Criteria

List each criterion.

Example:

AC-01
Login form is displayed.

AC-02
Email is required.

AC-03
Valid credentials authenticate the user.

Each criterion should be editable.

Gherkin

Show syntax-highlighted Gherkin.

Example:

Feature: User authentication

Scenario: Successful login

Given I am on the login page
When I enter valid credentials
And I click "Login"
Then I should be redirected to the dashboard

Allow:

Edit

Save

Validate

Generate Playwright

Traceability

Display:

User Story
↓
Acceptance Criteria
↓
Gherkin
↓
Playwright
↓
Test Result

10. Gherkin page

Create a dedicated Gherkin workspace.

Display:

Features

Scenarios

Coverage

Validation status

Allow filtering by:

User Story

Feature

Status

Coverage

Provide:

"Validate Gherkin"

"Generate Playwright"

Buttons.

11. Automation page

Display Playwright tests.

Example:

login.spec.ts

User Story:
QA-42

Scenario:
Successful login

Status:
PASSED

Last execution:
Today

Duration:
1.2s

Actions:

View

Run

Regenerate

12. Test result detail

Display:

Test name

User Story

Gherkin scenario

Execution date

Duration

Status

If failed:

Error message

Screenshot

Trace

Console output

Create a clear visual distinction between:

PASSED

FAILED

SKIPPED

13. Coverage page

Create a QA coverage dashboard.

Metrics:

User Stories

31 total

29 with Gherkin

21 automated

Acceptance Criteria

124 total

109 covered

Coverage:

87.9%

Display charts for:

User Story coverage

Acceptance Criteria coverage

Gherkin coverage

Automation coverage

Display uncovered items.

Example:

⚠ AC-04 Password reset requires additional automation.

14. Settings

Sections:

Project

Project name

Repository

Branch

GitHub

Connection status

Jira

Connection status

Project key

AI

Current provider:

Ollama

Status:

Connected / Disconnected

Playwright

Test directory

Base URL

Browser configuration

All settings should eventually be retrieved through the backend API.

15. API abstraction

Create:

src/api/

Do NOT put business logic directly into React components.

Create an API client layer.

Example:

src/api/client.ts

src/api/projects.ts

src/api/analysis.ts

src/api/stories.ts

src/api/gherkin.ts

src/api/tests.ts

src/api/coverage.ts

Use mocked implementations for Phase 1.

The frontend should be able to switch from:

Mock API

to:

Python FastAPI

without rewriting the UI.

Use TypeScript interfaces for all API objects.

16. Data models

Create TypeScript models corresponding to the future backend.

Project:

{
id,
name,
repository,
branch,
jiraProject,
status,
lastAnalysis
}

Feature:

{
id,
projectId,
name,
description,
confidence,
sourceFiles,
status
}

UserStory:

{
id,
featureId,
title,
description,
confidence,
sourceFiles,
acceptanceCriteria,
gherkinScenarios,
jiraKey,
status
}

AcceptanceCriterion:

{
id,
userStoryId,
text,
covered
}

GherkinScenario:

{
id,
userStoryId,
feature,
scenario,
given,
when,
then,
status
}

PlaywrightTest:

{
id,
userStoryId,
gherkinScenarioId,
file,
status,
lastRun
}

17. Mock data

Create realistic mock data for:

3 projects

10+ User Stories

20+ Gherkin scenarios

10+ Playwright tests

test results

coverage

Use a fictional application such as an e-commerce application.

Do NOT use real credentials or real repositories.

18. UX requirements

The application must be:

responsive

fast

clean

professional

easy to understand

Use progressive disclosure.

Do not overload the user with technical information.

Functional QA information should be the primary information.

Technical information such as source files should be available but secondary.

19. Important design principle

The application is NOT an AI chatbot.

Do not create a ChatGPT-like interface as the primary UX.

The main interaction is:

Analyze

→ Review

→ Approve

→ Synchronize

→ Automate

→ Execute

→ Measure

20. Future API compatibility

The frontend must be compatible with this future backend:

FastAPI

/api/v1/projects
/api/v1/analyses
/api/v1/features
/api/v1/stories
/api/v1/gherkin
/api/v1/tests
/api/v1/coverage
/api/v1/jobs

Long-running operations must support:

job_id

status

progress

The frontend must therefore support asynchronous operation states.

21. Do NOT implement in Phase 1

Do not implement:

AI

Ollama

GitHub API

Git cloning

Jira API

Playwright execution

code analysis

authentication backend

billing

multi-tenant backend

Only prepare the frontend architecture for them.

22. Phase 1 acceptance criteria

The Phase 1 application is complete when:

A user can navigate the complete application.

A user can create a mock project.

A project dashboard displays realistic QA metrics.

A repository analysis workflow can be visually simulated.

User Stories can be reviewed.

Acceptance Criteria can be viewed and edited.

Gherkin scenarios can be viewed and edited.

Playwright tests can be viewed.

Test results can be displayed.

Coverage can be displayed.

All frontend data access goes through the API abstraction.

No QA business logic is embedded in React components.

The application is ready to connect to the future Python/FastAPI backend.

At the end of Phase 1, provide:

project structure

components created

API abstraction

TypeScript models

mock data

instructions for replacing the mock API with the FastAPI backend.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/8b1b38fc-dc00-4836-a762-990bfb970ee6).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
