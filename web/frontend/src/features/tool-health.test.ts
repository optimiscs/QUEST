import { describe, expect, it } from 'vitest';
import { summarize, historicalSeries, eventKey, filterEvents } from './tool-health';

describe('tool health statistics', () => {
  it('uses completed calls as denominator, keeps real zero results separate', () => {
    const rows = [{status:'success',zeroResults:true},{status:'failed',partial:true},{status:'unknown'},{status:'pending'},{status:'excluded'}];
    expect(summarize(rows)).toMatchObject({rate:50,zero:1,partial:1,unknown:1,pending:1,excluded:1});
    expect(summarize([]).rate).toBeNull();
  });
  it('uses elapsed time, weights calls, and excludes missing timestamps from history only', () => {
    const rows=[{status:'failed',elapsedSeconds:90},{status:'success',elapsedSeconds:10},{status:'success',elapsedSeconds:null}];
    expect(historicalSeries(rows)).toEqual([{x:60,y:100,n:1},{x:120,y:50,n:2}]);
    expect(summarize(rows).rate).toBeCloseTo(66.6667);
  });
  it('separates same trace IDs across datasets and supports status/reason intersection', () => {
    expect(eventKey('step39','row0001')).not.toEqual(eventKey('step76','row0001'));
    const rows=[{status:'failed',reasons:['超时']},{status:'success',reasons:[],zeroResults:true}];
    expect(filterEvents(rows,'failed','超时')).toHaveLength(1);
    expect(filterEvents(rows,'zero','')).toEqual([rows[1]]);
  });
});
