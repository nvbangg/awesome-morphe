import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { Providers } from "./components/Providers";
import "./index.css";

const rootElement = document.getElementById("app");
if (!rootElement) throw new Error("Failed to find the root element");

createRoot(rootElement).render(
	<StrictMode>
		<Providers>
			<App />
		</Providers>
	</StrictMode>,
);
