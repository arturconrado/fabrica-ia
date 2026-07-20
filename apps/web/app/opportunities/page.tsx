import { OperationalIndex } from "@/components/missions/OperationalIndex";

export default function OpportunitiesPage() {
  return <OperationalIndex endpoint="/api/v1/opportunities" title="Oportunidades" description="Demandas registradas no intake, com estágio e validação persistidos." emptyDescription="Registre uma demanda real na Fábrica para iniciar o pipeline." hrefPrefix="/opportunities" kind="opportunity" />;
}
