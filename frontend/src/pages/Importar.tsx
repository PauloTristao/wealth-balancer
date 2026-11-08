import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Classe, type Manual } from "../api";
import { CLASS_LABEL, fmtBRL, fmtDate } from "../format";

const EMPTY: Manual = {
  nome: "", classe: "RF", subtipo: "", instituicao: "", valor_aplicado: 0, valor_atual: 0,
  reserva_emergencia: false, obs: "",
};
const input = "card w-full px-2 py-1.5 text-sm";

export default function ImportarPage() {
  const qc = useQueryClient();
  const invalidate = () => ["dashboard", "income", "imports", "manuals"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));

  const imports = useQuery({ queryKey: ["imports"], queryFn: api.imports });
  const manuals = useQuery({ queryKey: ["manuals"], queryFn: api.manuals });
  const [files, setFiles] = useState<File[]>([]);
  const upload = useMutation({ mutationFn: api.upload, onSuccess: invalidate });

  const [form, setForm] = useState<Manual>(EMPTY);
  const save = useMutation({ mutationFn: api.saveManual, onSuccess: () => { setForm(EMPTY); invalidate(); } });
  const del = useMutation({ mutationFn: api.deleteManual, onSuccess: invalidate });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Importar e ajustes</h1>

      <div className="card space-y-3 p-5">
        <div className="font-semibold">Importar relatórios da B3</div>
        <p className="text-sm text-2">
          Área do Investidor B3 → Extratos → <b>Movimentação</b> e <b>Negociação</b> → exportar Excel. Pode enviar o
          período todo ou só o mês: linhas já importadas são ignoradas automaticamente.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            multiple
            accept=".xlsx,.xls,.csv"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="text-sm"
          />
          <button
            className="card px-3 py-1.5 text-sm font-semibold"
            disabled={!files.length || upload.isPending}
            onClick={() => upload.mutate(files)}
          >
            {upload.isPending ? "Importando…" : "Importar"}
          </button>
        </div>
        {upload.data && (
          <ul className="text-sm">
            {upload.data.resultados.map((r, i) => (
              <li key={i}>
                {"erro" in r ? (
                  <span className="neg">
                    {String(r.arquivo)}: {String(r.erro)}
                  </span>
                ) : (
                  <span>
                    ✓ {String(r.arquivo)} ({String(r.tipo)}): {String(r.novas)} linhas novas, {String(r.duplicadas)} já
                    existentes
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {upload.error && <p className="neg text-sm">{String(upload.error)}</p>}
      </div>

      <div className="card p-5">
        <div className="mb-3 font-semibold">Histórico de importações</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-2">
              <th className="py-1">Arquivo</th><th>Tipo</th><th>Período</th><th className="text-right">Linhas</th>
              <th className="text-right">Novas</th><th className="text-right">Importado em</th>
            </tr>
          </thead>
          <tbody>
            {imports.data?.map((l) => (
              <tr key={l.id} className="num border-t" style={{ borderColor: "var(--grid)" }}>
                <td className="py-1.5">{l.arquivo}</td>
                <td>{l.tipo}</td>
                <td>{l.periodo[0] && `${fmtDate(l.periodo[0])} a ${fmtDate(l.periodo[1])}`}</td>
                <td className="text-right">{l.linhas}</td>
                <td className="text-right">{l.novas}</td>
                <td className="text-right">{l.importado_em.slice(0, 16).replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card space-y-4 p-5">
        <div>
          <div className="font-semibold">Posições fora da B3</div>
          <p className="text-sm text-2">
            Reserva de emergência, CDB/LCI em banco, fundos, cripto etc. Atualize o valor atual quando quiser. Itens
            marcados como reserva ficam fora do balanceamento.
          </p>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {manuals.data?.map((m) => (
              <tr key={m.id} className="num border-t" style={{ borderColor: "var(--grid)" }}>
                <td className="py-1.5 font-medium">{m.nome}</td>
                <td>{CLASS_LABEL[m.classe]}{m.reserva_emergencia ? " · reserva" : ""}</td>
                <td>{m.instituicao}</td>
                <td className="text-right">aplicado {fmtBRL(m.valor_aplicado)}</td>
                <td className="text-right">atual {fmtBRL(m.valor_atual)}</td>
                <td className="text-right text-muted">{m.data_ref && fmtDate(m.data_ref)}</td>
                <td className="text-right">
                  <button className="text-2 underline" onClick={() => setForm(m)}>editar</button>{" "}
                  <button className="neg underline" onClick={() => m.id && del.mutate(m.id)}>excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <form
          className="grid grid-cols-2 gap-3 md:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(form);
          }}
        >
          <label className="text-sm">Nome
            <input className={input} required value={form.nome} onChange={(e) => setForm({ ...form, nome: e.target.value })} />
          </label>
          <label className="text-sm">Classe
            <select className={input} value={form.classe} onChange={(e) => setForm({ ...form, classe: e.target.value as Classe })}>
              {(["ACAO", "FII", "RF", "INTL", "OUTROS"] as Classe[]).map((c) => (
                <option key={c} value={c}>{CLASS_LABEL[c]}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">Tipo (ex.: CDB, LCI, Cripto)
            <input className={input} value={form.subtipo} onChange={(e) => setForm({ ...form, subtipo: e.target.value })} />
          </label>
          <label className="text-sm">Instituição
            <input className={input} value={form.instituicao} onChange={(e) => setForm({ ...form, instituicao: e.target.value })} />
          </label>
          <label className="text-sm">Valor aplicado (R$)
            <input className={input} type="number" step="0.01" value={form.valor_aplicado}
              onChange={(e) => setForm({ ...form, valor_aplicado: Number(e.target.value) })} />
          </label>
          <label className="text-sm">Valor atual (R$)
            <input className={input} type="number" step="0.01" value={form.valor_atual}
              onChange={(e) => setForm({ ...form, valor_atual: Number(e.target.value) })} />
          </label>
          <label className="flex items-end gap-2 pb-2 text-sm">
            <input type="checkbox" checked={form.reserva_emergencia}
              onChange={(e) => setForm({ ...form, reserva_emergencia: e.target.checked })} />
            Reserva de emergência
          </label>
          <div className="flex items-end gap-2">
            <button className="card px-3 py-1.5 text-sm font-semibold" type="submit" disabled={save.isPending}>
              {form.id ? "Salvar alterações" : "Adicionar"}
            </button>
            {form.id && (
              <button type="button" className="text-sm text-2 underline" onClick={() => setForm(EMPTY)}>cancelar</button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
