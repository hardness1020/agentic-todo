// AuthScreen.jsx — login screen (cosmetic; any input logs you in).
function AuthScreen({ onLogin }) {
  const [email, setEmail] = React.useState("you@todo.app");
  const [pw, setPw] = React.useState("••••••••");
  const [mode, setMode] = React.useState("login");
  return (
    <div className="auth">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="mark"><Icon name="check" size={25} stroke={3} /></span>
          <span className="wm">ToDo</span>
        </div>
        <h1>{mode === "login" ? "Welcome back" : "Create your account"}</h1>
        <p className="sub">Your calm, AI-powered to-do list.</p>
        <form onSubmit={(e) => { e.preventDefault(); onLogin(email); }}>
          <div className="field">
            <label>Email</label>
            <input value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field">
            <label>Password</label>
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
          </div>
          <button className="btn-primary" type="submit">
            {mode === "login" ? "Log in" : "Sign up"}
          </button>
        </form>
        <div className="switch">
          {mode === "login" ? "New here? " : "Have an account? "}
          <a onClick={() => setMode(mode === "login" ? "signup" : "login")}>
            {mode === "login" ? "Create an account" : "Log in"}
          </a>
        </div>
      </div>
    </div>
  );
}
window.AuthScreen = AuthScreen;
