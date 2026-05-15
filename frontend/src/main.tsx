import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { Safe } from "./Safe";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Safe label="The app" reload>
      <App />
    </Safe>
  </StrictMode>,
);
