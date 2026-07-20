import { OperationalIndex } from "@/components/missions/OperationalIndex";

export default function ProgramsPage() {
  return <OperationalIndex endpoint="/api/v1/programs" title="Programas" description="Programas reais que organizam projetos e entregas do tenant." emptyDescription="Crie o primeiro programa durante o onboarding operacional do cliente." hrefPrefix="/programs" kind="program" />;
}
