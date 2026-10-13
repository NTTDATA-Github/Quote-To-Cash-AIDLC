import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ArrowRightLeft } from "lucide-react";

import { useAuth } from "../../auth/AuthContext";
import { ERP_BRANDS, type ErpBrand } from "./brandIcons";

function IconColumn({ order, className }: { order: number[]; className: string }) {
  const looped = [...order, ...order];
  return (
    <div className={`icon-rain__col ${className}`} aria-hidden="true">
      {looped.map((idx, i) => {
        const erp = ERP_BRANDS[idx];
        return (
          <span className={`icon-chip ${erp.status === "soon" ? "icon-chip--soon" : ""}`} key={i}>
            {erp.svg ? (
              <span dangerouslySetInnerHTML={{ __html: erp.svg }} />
            ) : (
              <span className="icon-chip__text">{erp.name.slice(0, 2).toUpperCase()}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}

const ALL_IDX = ERP_BRANDS.map((_, i) => i);

function ErpBadge({ erp }: { erp: ErpBrand }) {
  return (
    <span className={`erp-chip erp-chip--${erp.status}`}>
      {erp.svg ? (
        <span className="erp-chip__mark" dangerouslySetInnerHTML={{ __html: erp.svg }} />
      ) : (
        <span className="erp-chip__mark erp-chip__mark--text">{erp.name.slice(0, 2).toUpperCase()}</span>
      )}
      {erp.name}
      <span className="erp-chip__status">{erp.status === "live" ? "Live" : "Soon"}</span>
    </span>
  );
}

export function LoginPage() {
  const { isAuthenticated, isLoading, error, signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  if (isAuthenticated) return <Navigate to="/" replace />;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    void signIn(username, password);
  }

  return (
    <div className="authscreen">
      <div className="authscreen__art">
        <div className="icon-rain">
          <IconColumn order={ALL_IDX} className="icon-rain__col--a" />
          <IconColumn order={[...ALL_IDX].reverse()} className="icon-rain__col--b" />
          <IconColumn order={ALL_IDX.slice(2).concat(ALL_IDX.slice(0, 2))} className="icon-rain__col--c" />
        </div>
        <div className="authscreen__pitch">
          <h2>One console for every ERP.</h2>
          <p>Connect resellers to your ERPs, route every order, and track it from read to confirmed to closed.</p>
          <div className="erp-status">
            {ERP_BRANDS.map((erp) => (
              <ErpBadge key={erp.name} erp={erp} />
            ))}
          </div>
        </div>
      </div>
      <div className="authscreen__form">
       <div className="authscreen__formcenter">
        <section className="authcard" aria-label="Sign in">
          <div className="authbrand">
            <div className="brand__mark">
              <ArrowRightLeft size={20} strokeWidth={2.25} />
            </div>
            <div className="authbrand__text">
              <span className="authbrand__name">Order-to-Cash</span>
              <span className="authbrand__sub">Operator Console</span>
            </div>
          </div>
          <p className="authcard__lead">Sign in to route reseller orders and track order-to-cash across your ERPs.</p>
          <form className="stack" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="username">Username</label>
              <input className="input" id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                className="input"
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            {error && <span className="formerr">{error}</span>}
            <button className="erp-btn erp-btn--primary" type="submit" disabled={isLoading}>
              {isLoading ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </section>
       </div>
        <div className="authscreen__foot">
          <span className="side-foot__label">Powered by</span>
          <img className="side-foot__logo" src="/ntt-logo.png" alt="NTT" />
        </div>
      </div>
    </div>
  );
}
