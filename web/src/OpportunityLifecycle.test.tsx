import {render,screen} from '@testing-library/react';
import {describe,it,expect} from 'vitest';
import {OpportunityLifecycle} from './OpportunityLifecycle';
describe('frozen lifecycle provenance',()=>{
 it('keeps old history explicitly unknown without filling current state',()=>{render(<OpportunityLifecycle next="DEEP_RESEARCH_NOT_PROVIDED"/>);expect(screen.getByText(/历史运行未冻结生命周期/)).toBeTruthy();expect(screen.getByText(/本历史运行当时未提供深研/)).toBeTruthy();});
 it('shows source and read-only state separately from candidate permission',()=>{render(<OpportunityLifecycle snapshot={{schema_version:'1.0',instrument_id:'i',as_of:'now',status:'AVAILABLE',reason:'RECORDED_INITIAL_STATE',state:'WATCH',source_record_id:'original-state',source_version:1,effective_at:'then',recorded_at:'then',thesis_version_id:null,decision_id:null,source_hash:'hash'}} next="EXPLICIT_RESEARCH_CONSENT_REQUIRED"/>);expect(screen.getByText(/生命周期：WATCH/)).toBeTruthy();expect(screen.getByText(/original-state/)).toBeTruthy();expect(screen.getByText(/逐个明确同意后研究/)).toBeTruthy();});
});
