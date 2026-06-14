# Market Watch Dashboard

React 19, Vite, TypeScript, Tailwind CSS, and daisyUI user interface for the Market Watch Assistant.

---

## 📖 Component Documentation
For a detailed guide on component features, polling data caches, routing layouts, and the API wrapper, see **[React Dashboard Overview](../docs/dashboard.md)**.

---

## 🚀 Development Scripts

Inside the `dashboard/` directory, you can run:

### Setup
```bash
npm install
```

### Start Development Server
Runs the web app in development mode with hot-reloading (defaults to port `5173`):
```bash
npm run dev
```

### Build for Production
Compiles and bundles optimization assets under `dist/`:
```bash
npm run build
```

### Run Tests
Executes unit and component tests via Vitest:
```bash
npm run test
```

### Run Linter
Checks code style and typescript compiler rules:
```bash
npm run lint
```

### Run End-to-End Tests
Executes integration tests via Playwright:
```bash
npm run e2e
```

---

## ⚙️ Environment Variables
The dashboard reads the following environment parameters:
- `VITE_API_BASE_URL`: The API target address (defaults to `http://localhost:8000` if not set).
- `VITE_API_AUTH_TOKEN`: The bearer authentication key used to permit write actions on the backend.
