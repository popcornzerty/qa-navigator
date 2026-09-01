import type {
  AcceptanceCriterion,
  ActivityEvent,
  AnalysisJob,
  Feature,
  GherkinScenario,
  PlaywrightTest,
  Project,
  ProjectSettings,
  UserStory,
} from "../../types/models";

/**
 * Mock dataset for a fictional e-commerce application ("Atlas Commerce").
 * No real repositories or credentials.
 */

export const projects: Project[] = [
  {
    id: "prj-atlas-store",
    name: "Atlas Commerce Storefront",
    repository: "github.com/atlas-demo/atlas-storefront",
    repositorySource: "github",
    branch: "main",
    jiraProject: "ATL",
    jiraConnection: "connected",
    aiProvider: "ollama",
    status: "ready",
    lastAnalysis: "2026-08-31T09:12:00Z",
    storyCount: 8,
    automatedTestCount: 8,
  },
  {
    id: "prj-atlas-api",
    name: "Atlas Commerce API",
    repository: "github.com/atlas-demo/atlas-api",
    repositorySource: "github",
    branch: "develop",
    jiraProject: "API",
    jiraConnection: "connected",
    aiProvider: "ollama",
    status: "analyzing",
    lastAnalysis: "2026-08-28T16:40:00Z",
    storyCount: 3,
    automatedTestCount: 3,
  },
  {
    id: "prj-atlas-admin",
    name: "Atlas Admin Console",
    repository: "local://workspaces/atlas-admin",
    repositorySource: "local",
    branch: "feature/qa-baseline",
    jiraProject: null,
    jiraConnection: "not_connected",
    aiProvider: "ollama",
    status: "never_analyzed",
    lastAnalysis: null,
    storyCount: 1,
    automatedTestCount: 1,
  },
];

export const features: Feature[] = [
  {
    id: "ft-auth",
    projectId: "prj-atlas-store",
    name: "Authentication",
    description: "Sign in, sign out and password recovery for shoppers.",
    confidence: 0.94,
    sourceFiles: ["src/routes/login.tsx", "src/lib/auth.ts", "src/components/LoginForm.tsx"],
    status: "confirmed",
  },
  {
    id: "ft-catalog",
    projectId: "prj-atlas-store",
    name: "Product Catalog",
    description: "Product listing, search, filtering and product detail pages.",
    confidence: 0.91,
    sourceFiles: ["src/routes/products.tsx", "src/components/ProductGrid.tsx"],
    status: "confirmed",
  },
  {
    id: "ft-cart",
    projectId: "prj-atlas-store",
    name: "Cart",
    description: "Cart management: add, update quantity, remove, promo codes.",
    confidence: 0.88,
    sourceFiles: ["src/routes/cart.tsx", "src/store/cart.ts"],
    status: "confirmed",
  },
  {
    id: "ft-checkout",
    projectId: "prj-atlas-store",
    name: "Checkout",
    description: "Address, shipping method, payment and order confirmation.",
    confidence: 0.85,
    sourceFiles: ["src/routes/checkout.tsx", "src/lib/payment.ts"],
    status: "confirmed",
  },
  {
    id: "ft-orders",
    projectId: "prj-atlas-api",
    name: "Orders",
    description: "Order history, order detail and shipment tracking endpoints.",
    confidence: 0.79,
    sourceFiles: ["app/routers/orders.py", "app/services/shipping.py"],
    status: "detected",
  },
  {
    id: "ft-account",
    projectId: "prj-atlas-admin",
    name: "Back-office Account",
    description: "Operator accounts, roles and permission management.",
    confidence: 0.62,
    sourceFiles: ["src/pages/Users.tsx"],
    status: "detected",
  },
];

interface StorySeed {
  key: string;
  projectId: string;
  featureId: string;
  epic: string;
  title: string;
  description: string;
  confidence: number;
  jiraKey: string | null;
  status: UserStory["status"];
  sourceFiles: string[];
  criteria: [string, boolean][];
  scenarios: {
    scenario: string;
    given: string[];
    when: string[];
    then: string[];
    status: GherkinScenario["status"];
  }[];
}

const seeds: StorySeed[] = [
  {
    key: "US-101",
    projectId: "prj-atlas-store",
    featureId: "ft-auth",
    epic: "Shopper identity",
    title: "Sign in with valid credentials",
    description:
      "As a returning shopper, I want to sign in with my email and password so that I can access my account and order history.",
    confidence: 0.94,
    jiraKey: "ATL-482",
    status: "approved",
    sourceFiles: ["src/routes/login.tsx", "src/lib/auth.ts"],
    criteria: [
      ["The login form is displayed with email and password fields.", true],
      ["Email is required and must be a valid address.", true],
      ["Valid credentials authenticate the shopper and open the dashboard.", true],
      ["A session is persisted across page reloads.", true],
    ],
    scenarios: [
      {
        scenario: "Successful login",
        given: ["I am on the login page"],
        when: ['I enter valid credentials', 'I click "Login"'],
        then: ["I should be redirected to the dashboard"],
        status: "automated",
      },
      {
        scenario: "Session persists after reload",
        given: ["I am signed in as a shopper"],
        when: ["I reload the page"],
        then: ["I should still be signed in"],
        status: "valid",
      },
    ],
  },
  {
    key: "US-102",
    projectId: "prj-atlas-store",
    featureId: "ft-auth",
    epic: "Shopper identity",
    title: "Reject invalid credentials",
    description:
      "As a shopper, I want a clear error message when my credentials are wrong so that I understand why sign in failed.",
    confidence: 0.9,
    jiraKey: "ATL-483",
    status: "approved",
    sourceFiles: ["src/routes/login.tsx", "src/components/LoginForm.tsx"],
    criteria: [
      ["An invalid password shows an inline error message.", true],
      ["The shopper remains on the login page.", true],
      ["The account is locked after five consecutive failures.", false],
    ],
    scenarios: [
      {
        scenario: "Login with a wrong password",
        given: ["I am on the login page"],
        when: ['I enter an invalid password', 'I click "Login"'],
        then: ['I should see the error "Invalid email or password"'],
        status: "automated",
      },
    ],
  },
  {
    key: "US-103",
    projectId: "prj-atlas-store",
    featureId: "ft-auth",
    epic: "Shopper identity",
    title: "Reset a forgotten password",
    description:
      "As a shopper who forgot their password, I want to request a reset link so that I can regain access to my account.",
    confidence: 0.71,
    jiraKey: "ATL-490",
    status: "needs_review",
    sourceFiles: ["src/routes/forgot-password.tsx"],
    criteria: [
      ["A reset link is sent to a known email address.", true],
      ["Unknown emails receive the same neutral confirmation.", false],
      ["Reset links expire after 60 minutes.", false],
    ],
    scenarios: [
      {
        scenario: "Request a reset link",
        given: ["I am on the forgot password page"],
        when: ["I submit my email address"],
        then: ["I should see a confirmation message"],
        status: "valid",
      },
    ],
  },
  {
    key: "US-104",
    projectId: "prj-atlas-store",
    featureId: "ft-catalog",
    epic: "Product discovery",
    title: "Filter products by category",
    description:
      "As a shopper, I want to filter the catalog by category so that I can find relevant products faster.",
    confidence: 0.96,
    jiraKey: "ATL-512",
    status: "approved",
    sourceFiles: ["src/routes/products.tsx", "src/components/CategoryFilter.tsx"],
    criteria: [
      ["All categories are listed in the filter panel.", true],
      ["Selecting a category updates the product grid.", true],
      ["The active filter is reflected in the URL.", true],
      ["Clearing filters restores the full catalog.", true],
    ],
    scenarios: [
      {
        scenario: "Filter by a single category",
        given: ["I am on the products page"],
        when: ['I select the category "Outdoor"'],
        then: ["I should only see outdoor products"],
        status: "automated",
      },
      {
        scenario: "Clear the active filter",
        given: ['I filtered products by "Outdoor"'],
        when: ['I click "Clear filters"'],
        then: ["I should see the full catalog"],
        status: "automated",
      },
    ],
  },
  {
    key: "US-105",
    projectId: "prj-atlas-store",
    featureId: "ft-catalog",
    epic: "Product discovery",
    title: "Search products by keyword",
    description:
      "As a shopper, I want to search products by keyword so that I can reach a specific item directly.",
    confidence: 0.89,
    jiraKey: "ATL-514",
    status: "created",
    sourceFiles: ["src/components/SearchBar.tsx", "src/lib/search.ts"],
    criteria: [
      ["Results are shown after two characters.", true],
      ["An empty result set shows an explanatory message.", true],
      ["Search is case insensitive.", true],
    ],
    scenarios: [
      {
        scenario: "Search returns matching products",
        given: ["I am on the products page"],
        when: ['I search for "tent"'],
        then: ["I should see products matching the keyword"],
        status: "automated",
      },
      {
        scenario: "Search returns no result",
        given: ["I am on the products page"],
        when: ['I search for "zzzz"'],
        then: ["I should see an empty state message"],
        status: "valid",
      },
    ],
  },
  {
    key: "US-106",
    projectId: "prj-atlas-store",
    featureId: "ft-cart",
    epic: "Cart and checkout",
    title: "Add a product to the cart",
    description:
      "As a shopper, I want to add a product to my cart so that I can purchase it later in the session.",
    confidence: 0.93,
    jiraKey: "ATL-530",
    status: "approved",
    sourceFiles: ["src/routes/products.$id.tsx", "src/store/cart.ts"],
    criteria: [
      ["The cart badge count increases by one.", true],
      ["The product appears in the cart drawer.", true],
      ["Out-of-stock products cannot be added.", true],
    ],
    scenarios: [
      {
        scenario: "Add an available product",
        given: ["I am on a product detail page"],
        when: ['I click "Add to cart"'],
        then: ["The cart should contain 1 item"],
        status: "automated",
      },
      {
        scenario: "Add an out-of-stock product",
        given: ["I am on an out-of-stock product page"],
        when: ["I look at the purchase actions"],
        then: ['The "Add to cart" button should be disabled'],
        status: "valid",
      },
    ],
  },
  {
    key: "US-107",
    projectId: "prj-atlas-store",
    featureId: "ft-cart",
    epic: "Cart and checkout",
    title: "Update item quantity in the cart",
    description:
      "As a shopper, I want to change item quantities in my cart so that I order the right amount.",
    confidence: 0.87,
    jiraKey: null,
    status: "draft",
    sourceFiles: ["src/routes/cart.tsx"],
    criteria: [
      ["Quantity can be increased up to available stock.", true],
      ["Setting quantity to zero removes the line.", true],
      ["The cart total recalculates immediately.", true],
      ["Stock limits show a warning message.", false],
    ],
    scenarios: [
      {
        scenario: "Increase quantity",
        given: ["My cart contains 1 item"],
        when: ["I set the quantity to 3"],
        then: ["The cart total should be recalculated"],
        status: "automated",
      },
      {
        scenario: "Remove a line by setting quantity to zero",
        given: ["My cart contains 1 item"],
        when: ["I set the quantity to 0"],
        then: ["The cart should be empty"],
        status: "draft",
      },
    ],
  },
  {
    key: "US-108",
    projectId: "prj-atlas-store",
    featureId: "ft-checkout",
    epic: "Cart and checkout",
    title: "Complete checkout with a saved address",
    description:
      "As a signed-in shopper, I want to check out with a saved address so that I can order in fewer steps.",
    confidence: 0.84,
    jiraKey: "ATL-561",
    status: "out_of_sync",
    sourceFiles: ["src/routes/checkout.tsx", "src/lib/payment.ts"],
    criteria: [
      ["Saved addresses are pre-selected.", true],
      ["Shipping method selection is required.", true],
      ["Payment failure keeps the shopper on the payment step.", false],
      ["A confirmed order shows an order number.", true],
    ],
    scenarios: [
      {
        scenario: "Checkout with saved address",
        given: ["I am signed in with a saved address", "My cart contains 2 items"],
        when: ["I confirm shipping and payment"],
        then: ["I should see an order confirmation number"],
        status: "automated",
      },
      {
        scenario: "Payment declined",
        given: ["I am on the payment step"],
        when: ["My card is declined"],
        then: ["I should stay on the payment step with an error"],
        status: "invalid",
      },
    ],
  },
  {
    key: "US-109",
    projectId: "prj-atlas-api",
    featureId: "ft-orders",
    epic: "Order lifecycle",
    title: "List orders for the current customer",
    description:
      "As an API consumer, I want to list the authenticated customer's orders so that the storefront can show order history.",
    confidence: 0.82,
    jiraKey: "API-118",
    status: "approved",
    sourceFiles: ["app/routers/orders.py"],
    criteria: [
      ["Only the authenticated customer's orders are returned.", true],
      ["Results are paginated with a default page size of 20.", true],
      ["Unauthenticated requests return 401.", true],
    ],
    scenarios: [
      {
        scenario: "List orders successfully",
        given: ["I am an authenticated customer"],
        when: ["I request my orders"],
        then: ["I should receive my paginated order list"],
        status: "automated",
      },
      {
        scenario: "Unauthenticated order listing",
        given: ["I have no valid token"],
        when: ["I request the orders endpoint"],
        then: ["I should receive a 401 response"],
        status: "valid",
      },
    ],
  },
  {
    key: "US-110",
    projectId: "prj-atlas-api",
    featureId: "ft-orders",
    epic: "Order lifecycle",
    title: "Track a shipment",
    description:
      "As a customer, I want to see the shipment status of an order so that I know when to expect delivery.",
    confidence: 0.76,
    jiraKey: "API-124",
    status: "needs_review",
    sourceFiles: ["app/services/shipping.py"],
    criteria: [
      ["Shipment status is returned for shipped orders.", true],
      ["Pending orders return an empty tracking payload.", true],
      ["Carrier errors degrade gracefully.", false],
    ],
    scenarios: [
      {
        scenario: "Track a shipped order",
        given: ["I have a shipped order"],
        when: ["I request its tracking information"],
        then: ["I should see the current shipment status"],
        status: "automated",
      },
    ],
  },
  {
    key: "US-111",
    projectId: "prj-atlas-api",
    featureId: "ft-orders",
    epic: "Order lifecycle",
    title: "Cancel an order before fulfilment",
    description:
      "As a customer, I want to cancel an order that has not shipped so that I am not charged for it.",
    confidence: 0.68,
    jiraKey: null,
    status: "draft",
    sourceFiles: ["app/routers/orders.py"],
    criteria: [
      ["Orders in status 'pending' can be cancelled.", true],
      ["Shipped orders cannot be cancelled.", false],
      ["Cancellation triggers a refund request.", false],
    ],
    scenarios: [
      {
        scenario: "Cancel a pending order",
        given: ["I have a pending order"],
        when: ["I cancel it"],
        then: ["The order status should be cancelled"],
        status: "draft",
      },
    ],
  },
  {
    key: "US-112",
    projectId: "prj-atlas-admin",
    featureId: "ft-account",
    epic: "Back-office administration",
    title: "Assign a role to an operator",
    description:
      "As an administrator, I want to assign roles to operators so that permissions match their responsibilities.",
    confidence: 0.59,
    jiraKey: null,
    status: "needs_review",
    sourceFiles: ["src/pages/Users.tsx"],
    criteria: [
      ["Available roles are listed for each operator.", true],
      ["Role change is audited.", false],
      ["Administrators cannot remove their own admin role.", false],
    ],
    scenarios: [
      {
        scenario: "Assign the support role",
        given: ["I am an administrator on the operators page"],
        when: ['I assign the role "Support" to an operator'],
        then: ["The operator should have the Support role"],
        status: "valid",
      },
    ],
  },
];

export const stories: UserStory[] = seeds.map((seed) => {
  const feature = features.find((f) => f.id === seed.featureId)!;
  const acceptanceCriteria: AcceptanceCriterion[] = seed.criteria.map(([text, covered], index) => ({
    id: `${seed.key}-AC-${String(index + 1).padStart(2, "0")}`,
    userStoryId: seed.key,
    text,
    covered,
  }));
  const gherkinScenarios: GherkinScenario[] = seed.scenarios.map((scenario, index) => ({
    id: `${seed.key}-SC-${index + 1}`,
    userStoryId: seed.key,
    feature: feature.name,
    scenario: scenario.scenario,
    given: scenario.given,
    when: scenario.when,
    then: scenario.then,
    status: scenario.status,
  }));

  return {
    id: seed.key,
    projectId: seed.projectId,
    featureId: seed.featureId,
    featureName: feature.name,
    epic: seed.epic,
    title: seed.title,
    description: seed.description,
    confidence: seed.confidence,
    sourceFiles: seed.sourceFiles,
    acceptanceCriteria,
    gherkinScenarios,
    jiraKey: seed.jiraKey,
    status: seed.status,
  };
});

interface TestSeed {
  storyKey: string;
  scenarioIndex: number;
  file: string;
  status: PlaywrightTest["status"];
  lastRun: string | null;
  durationMs: number;
  error?: string;
}

const testSeeds: TestSeed[] = [
  { storyKey: "US-101", scenarioIndex: 0, file: "tests/auth/login.spec.ts", status: "passed", lastRun: "2026-09-01T08:41:00Z", durationMs: 1200 },
  { storyKey: "US-102", scenarioIndex: 0, file: "tests/auth/login-invalid.spec.ts", status: "passed", lastRun: "2026-09-01T08:41:00Z", durationMs: 940 },
  { storyKey: "US-104", scenarioIndex: 0, file: "tests/catalog/filter-category.spec.ts", status: "passed", lastRun: "2026-09-01T08:42:00Z", durationMs: 1780 },
  { storyKey: "US-104", scenarioIndex: 1, file: "tests/catalog/clear-filters.spec.ts", status: "passed", lastRun: "2026-09-01T08:42:00Z", durationMs: 1310 },
  { storyKey: "US-105", scenarioIndex: 0, file: "tests/catalog/search.spec.ts", status: "skipped", lastRun: "2026-09-01T08:42:00Z", durationMs: 0 },
  { storyKey: "US-106", scenarioIndex: 0, file: "tests/cart/add-to-cart.spec.ts", status: "passed", lastRun: "2026-09-01T08:43:00Z", durationMs: 1490 },
  {
    storyKey: "US-107",
    scenarioIndex: 0,
    file: "tests/cart/update-quantity.spec.ts",
    status: "failed",
    lastRun: "2026-09-01T08:43:00Z",
    durationMs: 4120,
    error:
      'TimeoutError: locator.click: Timeout 5000ms exceeded.\nwaiting for getByTestId("cart-qty-increase")',
  },
  {
    storyKey: "US-108",
    scenarioIndex: 0,
    file: "tests/checkout/saved-address.spec.ts",
    status: "failed",
    lastRun: "2026-09-01T08:44:00Z",
    durationMs: 6380,
    error:
      'expect(received).toContainText(expected)\nExpected: "Order confirmed"\nReceived: "Payment provider unavailable"',
  },
  { storyKey: "US-109", scenarioIndex: 0, file: "tests/api/orders-list.spec.ts", status: "passed", lastRun: "2026-08-31T18:02:00Z", durationMs: 620 },
  { storyKey: "US-109", scenarioIndex: 1, file: "tests/api/orders-unauthorized.spec.ts", status: "passed", lastRun: "2026-08-31T18:02:00Z", durationMs: 410 },
  {
    storyKey: "US-110",
    scenarioIndex: 0,
    file: "tests/api/shipment-tracking.spec.ts",
    status: "failed",
    lastRun: "2026-08-31T18:03:00Z",
    durationMs: 2870,
    error: "AssertionError: expected status 'in_transit' to equal 'shipped'",
  },
  { storyKey: "US-112", scenarioIndex: 0, file: "tests/admin/assign-role.spec.ts", status: "not_run", lastRun: null, durationMs: 0 },
];

export const tests: PlaywrightTest[] = testSeeds.map((seed, index) => {
  const story = stories.find((s) => s.id === seed.storyKey)!;
  const scenario = story.gherkinScenarios[seed.scenarioIndex]!;

  return {
    id: `pw-${String(index + 1).padStart(3, "0")}`,
    projectId: story.projectId,
    userStoryId: story.id,
    userStoryKey: story.jiraKey ?? story.id,
    gherkinScenarioId: scenario.id,
    scenario: scenario.scenario,
    file: seed.file,
    status: seed.status,
    lastRun: seed.lastRun,
    durationMs: seed.durationMs,
    result: {
      status: seed.status,
      executedAt: seed.lastRun,
      durationMs: seed.durationMs,
      ...(seed.error
        ? {
            errorMessage: seed.error,
            screenshot: `artifacts/${seed.file.split("/").pop()}/failure.png`,
            trace: `artifacts/${seed.file.split("/").pop()}/trace.zip`,
            consoleOutput: [
              "[info] navigated to https://staging.atlas-demo.test",
              "[warn] slow network response: /api/v1/cart (1284ms)",
              "[error] Uncaught (in promise) TypeError: cannot read property 'total'",
            ],
          }
        : {}),
    },
  };
});

export const activity: ActivityEvent[] = [
  { id: "ev-1", kind: "success", message: "Analysis completed on Atlas Commerce Storefront", at: "2026-09-01T09:14:00Z" },
  { id: "ev-2", kind: "info", message: "12 User Stories approved", at: "2026-09-01T08:58:00Z" },
  { id: "ev-3", kind: "success", message: "8 Playwright tests generated", at: "2026-09-01T08:12:00Z" },
  { id: "ev-4", kind: "error", message: "3 tests failed on tests/checkout", at: "2026-09-01T07:44:00Z" },
  { id: "ev-5", kind: "warning", message: "US-108 is out of sync with Jira ATL-561", at: "2026-08-31T19:20:00Z" },
];

export const analysisSteps: AnalysisJob["steps"] = [
  { key: "repository", label: "Repository", status: "completed", detail: "318 files retrieved" },
  { key: "architecture", label: "Architecture", status: "completed", detail: "React + TypeScript detected" },
  { key: "routes", label: "Routes", status: "completed", detail: "24 routes mapped" },
  { key: "components", label: "Components", status: "completed", detail: "162 components indexed" },
  { key: "apis", label: "APIs", status: "completed", detail: "38 endpoints referenced" },
  { key: "features", label: "Features", status: "running", detail: "Detecting functional features" },
  { key: "stories", label: "User Stories", status: "pending" },
  { key: "gherkin", label: "Gherkin", status: "pending" },
];

export const jobs = new Map<string, AnalysisJob>();

export const settings = new Map<string, ProjectSettings>(
  projects.map((project) => [
    project.id,
    {
      projectId: project.id,
      name: project.name,
      repository: project.repository,
      branch: project.branch,
      github: {
        status: project.repositorySource === "github" ? "connected" : "disconnected",
        account: project.repositorySource === "github" ? "atlas-demo" : null,
      },
      jira: { status: project.jiraConnection, projectKey: project.jiraProject },
      ai: { provider: project.aiProvider, model: "qwen2.5-coder:14b", status: "connected" },
      playwright: {
        testDirectory: "tests",
        baseUrl: "https://staging.atlas-demo.test",
        browsers: ["chromium", "firefox"],
        headless: true,
      },
    } satisfies ProjectSettings,
  ]),
);

export const featureList: Feature[] = features;
