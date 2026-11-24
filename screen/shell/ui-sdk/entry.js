// Experiment-only entry: register the @ui-sdk/web custom elements the new
// ot-* blocks are built on. Side-effect imports only; the shell (shell.js)
// creates these elements from sanitized model markup, the model never writes
// ui-* tags or JavaScript itself.
import "@ui-sdk/web/field";
import "@ui-sdk/web/input";
import "@ui-sdk/web/radio";
import "@ui-sdk/web/select";
