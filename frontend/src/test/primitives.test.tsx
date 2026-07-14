import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@/i18n";
import { Stars, SampleFlag } from "@/components/primitives";

describe("primitive components", () => {
  it("renders an accessible star rating", () => {
    render(<Stars rating={4} />);
    expect(screen.getByLabelText(/4 out of 5/i)).toBeInTheDocument();
  });

  it("shows the sample flag only when flagged", () => {
    const { rerender, container } = render(<SampleFlag show={false} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<SampleFlag show />);
    expect(screen.getByText(/demonstration only/i)).toBeInTheDocument();
  });
});
