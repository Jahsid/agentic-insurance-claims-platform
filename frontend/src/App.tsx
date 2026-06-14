import SubmitClaim from "./pages/SubmitClaim";

function App() {
  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b bg-white shadow-sm">
        <div className="mx-auto max-w-7xl px-6 py-5">
          <h1 className="text-3xl font-bold text-slate-900">
            Plum Claims Processing System
          </h1>

          <p className="mt-1 text-sm text-slate-600">
            AI-Powered Explainable
            Insurance Claims
            Adjudication Platform
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        <SubmitClaim />
      </main>
    </div>
  );
}

export default App;