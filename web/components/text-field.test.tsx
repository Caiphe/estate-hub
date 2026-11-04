import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TextField } from "./text-field";

describe("TextField", () => {
  it("keeps the workspace markup unchanged by default", () => {
    const html = renderToStaticMarkup(<TextField id="name" label="Full name" hint="As on file" error="Required" />);
    expect(html).toBe(
      '<div class="field"><label for="name">Full name</label><p id="name-hint" class="field-hint">As on file</p>' +
        '<input id="name" aria-invalid="true" aria-describedby="name-hint name-error"/>' +
        '<p id="name-error" class="field-error">Required</p></div>',
    );
  });

  it("places icons and trailing controls beside the input, never inside its label", () => {
    const html = renderToStaticMarkup(
      <TextField
        id="password"
        label="Password"
        appearance="site"
        leadingIcon={<svg aria-hidden="true" />}
        trailing={<button type="button">Show password</button>}
      />,
    );
    expect(html).toMatch(/<label for="password" class="[^"]*">Password<\/label>/);
    expect(html).toMatch(/<div class="relative"><span[^>]*><svg aria-hidden="true"><\/svg><\/span><input /);
    expect(html).toMatch(/<input [^>]*\/><span[^>]*><button type="button">Show password<\/button><\/span><\/div>/);
    // Room is reserved on both sides so text never runs under the icon or the control.
    expect(html).toMatch(/<input id="password" class="[^"]*\bpl-13\b[^"]*\bpr-14\b/);
  });

  it("describes the site input by its error", () => {
    const html = renderToStaticMarkup(<TextField id="email" label="Email address" appearance="site" error="Enter it." />);
    expect(html).toContain('aria-invalid="true" aria-describedby="email-error"');
    expect(html).toMatch(/<p id="email-error" class="[^"]*text-danger[^"]*">Enter it\.<\/p>/);
    expect(html).not.toContain('class="field');
  });
});
