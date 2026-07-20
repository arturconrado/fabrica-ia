import { OperationalIndex } from "@/components/missions/OperationalIndex";

export default function ComponentsPage() {
  return <OperationalIndex endpoint="/api/v1/component-instances" title="Componentes" description="Componentes contratados e instanciados nos projetos deste tenant." emptyDescription="Nenhum componente foi instanciado em um projeto autorizado." hrefPrefix="/components" kind="component" />;
}
