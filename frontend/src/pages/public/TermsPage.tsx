import { useLang } from "@/lib/nav";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const lang = useLang();
  return (
    <>
      <Seo title="Terms — Svaneti with Georgie" description="Terms of use." canonicalPath={`/${lang}/terms`} noindex />
      <Section>
        <Container size="narrow">
          <SectionHeading as="h1" title="Terms of Use" />
          <div className="prose-alpine">
            <p><em>Draft — requires owner review.</em></p>
            <p>Tour concepts, availability and prices shown on this site are indicative and confirmed directly with the guide. Mountain travel involves conditions that can change with weather and season.</p>
            <h2>Bookings & inquiries</h2>
            <p>Submitting an inquiry is a request, not a confirmed booking. The guide will confirm details, availability and pricing with you directly.</p>
          </div>
        </Container>
      </Section>
    </>
  );
}
