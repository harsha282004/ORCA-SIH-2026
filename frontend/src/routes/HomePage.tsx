import { AIIntelligenceSection } from "../components/sections/AIIntelligenceSection";
import { CapabilitiesSection } from "../components/sections/CapabilitiesSection";
import { CinematicHero } from "../components/cinematic/CinematicHero";
import { FeatureCardsSection } from "../components/sections/FeatureCardsSection";
import { FinalCtaSection } from "../components/sections/FinalCtaSection";
import { IntroSection } from "../components/sections/IntroSection";
import { ProblemSection } from "../components/sections/ProblemSection";
import { ProductExperienceSection } from "../components/sections/ProductExperienceSection";
import { TechnologySection } from "../components/sections/TechnologySection";

// The landing page is the cinematic marketing/storytelling experience —
// Ask ORCA and Route Planner now live on their own dedicated pages
// (/ask-orca, /route-planner); ProductExperienceSection is this page's
// entry point into them, not a duplicate of the tools themselves.
export function HomePage() {
  return (
    <main>
      <CinematicHero />
      <IntroSection />
      <FeatureCardsSection />
      <ProblemSection />
      <CapabilitiesSection />
      <AIIntelligenceSection />
      <ProductExperienceSection />
      <TechnologySection />
      <FinalCtaSection />
    </main>
  );
}
