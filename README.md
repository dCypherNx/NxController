# Nx Controller

Prova de conceito de uma integração mínima para Home Assistant. A configuração cria uma única entidade de sensor que apenas refletirá o endereço IP informado para o roteador ou ponto de acesso. Nenhum tráfego ou comando é enviado ao dispositivo.

## Instalação
1. Copie a pasta `custom_components/nx_controller` para o diretório `custom_components` do seu Home Assistant.
2. Reinicie o Home Assistant.
3. Acesse **Configurações → Dispositivos e Serviços → Adicionar Integração** e escolha **Nx Controller**.
4. Informe o endereço IP do roteador/AP e conclua o assistente.

O resultado será um dispositivo com um único sensor exibindo o IP fornecido, sem qualquer comunicação adicional.
