import { useLang } from "@/lib/nav";
import { Container, Section, SectionHeading } from "@/components/primitives";
import { Seo } from "@/components/site/Seo";

export function Component() {
  const lang = useLang();
  return (
    <>
      <Seo title="Privacy — Svaneti with Georgie" description="Privacy policy." canonicalPath={`/${lang}/privacy`} noindex />
      <Section>
        <Container size="narrow">
          <SectionHeading as="h1" title="Privacy Policy" />
          <div className="prose-alpine">
            <p><em>Draft — requires owner review.</em></p>
            <p>We collect only the information you provide through the inquiry form (such as your name, email and message) to respond to your trip request. We do not sell your data. Optional analytics load only with your consent.</p>
            <h2>What we collect</h2>
            <p>Contact details and trip preferences you submit, plus basic technical data required to operate the site securely.</p>
            <h2>Your choices</h2>
            <p>You may request access to or deletion of your inquiry data by contacting the owner.</p>
          </div>
        </Container>
      </Section>
    </>
  );
}
